"""
CLAP voice service — the one place that turns text into audible speech.

    from voice import speak
    speak("Opening Spotify.")

The rest of CLAP never deals with providers. The service:
  - picks the provider from configuration (no silent fallback to another voice)
  - strips markdown and pipelines long replies sentence-chunk by chunk
  - caches short fixed phrases ("Yes?") so acknowledgements start instantly
  - reports SPEAKING to the event hub only while audio is actually playing
  - exposes is_speaking() so the microphone can ignore CLAP's own voice
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import queue
import tempfile
import threading
import time
from pathlib import Path

from config import PROJECT_DIR, config
from events import AssistantState, hub
from voice.playback import AudioPlayer, PlaybackError
from voice.providers.base import TTSError, TTSProvider
from voice.text import split_for_speech, strip_markdown

log = logging.getLogger("clap.voice")

UNAVAILABLE = "Voice output is currently unavailable."
CACHE_MAX_CHARS = 120
ECHO_TAIL_SECONDS = 0.35   # keep the mic muted briefly after playback ends


def _discard(item: "tuple[str, bool]") -> None:
    """Delete a rendered temp file (cached files are kept)."""
    path, temporary = item
    if temporary:
        try:
            os.unlink(path)
        except OSError:
            pass


class VoiceService:
    def __init__(
        self,
        provider: "TTSProvider | None",
        player: "AudioPlayer | None" = None,
        cache_dir: "Path | None" = None,
        unavailable_reason: str = "",
    ) -> None:
        self.provider = provider
        self.player = player or AudioPlayer()
        self.cache_dir = cache_dir or (PROJECT_DIR / ".cache" / "tts")
        self._reason = unavailable_reason
        if provider and not self.player.available:
            self._reason = "No audio player found (afplay on macOS)."
        self.last_error = ""
        self._speak_lock = threading.Lock()
        self._speaking = threading.Event()
        self._tail_until = 0.0
        self._current_stop: "threading.Event | None" = None

    # ── Construction from .env ────────────────────────────────────────────

    @classmethod
    def from_config(cls) -> "VoiceService":
        choice = config.TTS_PROVIDER
        if choice in ("none", "off", "disabled"):
            return cls(None, unavailable_reason="Voice output is disabled (CLAP_TTS_PROVIDER=none).")

        if choice in ("", "elevenlabs"):
            if not (config.TTS_API_KEY and config.TTS_VOICE_ID):
                missing = [n for n, v in (("CLAP_TTS_API_KEY", config.TTS_API_KEY),
                                          ("CLAP_TTS_VOICE_ID", config.TTS_VOICE_ID)) if not v]
                return cls(None, unavailable_reason=f"Voice output is not configured ({', '.join(missing)} missing).")
            from voice.providers.elevenlabs import ElevenLabsProvider
            return cls(ElevenLabsProvider(config.TTS_API_KEY, config.TTS_VOICE_ID, config.TTS_MODEL_ID))

        if choice == "macos":
            try:
                from voice.providers.macos import MacOSSayProvider
                return cls(MacOSSayProvider(voice=config.TTS_VOICE_ID))
            except ValueError as exc:
                return cls(None, unavailable_reason=f"macOS voice unavailable: {exc}.")

        return cls(None, unavailable_reason=f"Unknown CLAP_TTS_PROVIDER '{choice}' (use elevenlabs, macos or none).")

    # ── Status ────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self.provider is not None and self.player.available

    def status(self) -> dict:
        return {
            "available": self.available,
            "provider": self.provider.name if self.provider else None,
            "voice": self.provider.voice_label if self.provider else None,
            "reference_voice": bool(self.provider and self.provider.reference_voice),
            "reason": "" if self.available else self._reason,
            "last_error": self.last_error,
        }

    def is_speaking(self) -> bool:
        return self._speaking.is_set() or time.monotonic() < self._tail_until

    # ── Speech ────────────────────────────────────────────────────────────

    def _cache_path(self, text: str) -> "Path | None":
        if len(text) > CACHE_MAX_CHARS or not self.provider:
            return None
        digest = hashlib.sha256(f"{self.provider.cache_key}\n{text}".encode()).hexdigest()[:32]
        return self.cache_dir / f"{digest}.{self.provider.audio_ext}"

    def _render(self, text: str) -> tuple[str, bool]:
        """Synthesise `text`; return (audio path, is_temporary)."""
        assert self.provider is not None
        cached = self._cache_path(text)
        if cached is not None:
            if cached.exists() and cached.stat().st_size > 0:
                return str(cached), False
            cached.parent.mkdir(parents=True, exist_ok=True)
            tmp = f"{cached}.part"
            self.provider.synthesize(text, tmp)
            os.replace(tmp, cached)
            return str(cached), False
        fd, path = tempfile.mkstemp(prefix="clap-tts-", suffix=f".{self.provider.audio_ext}")
        os.close(fd)
        self.provider.synthesize(text, path)
        return path, True

    def speak(
        self,
        text: str,
        announce: bool = True,
        then_state: AssistantState = AssistantState.STANDBY,
    ) -> bool:
        """
        Speak `text`, blocking until playback ends. Returns True on success.

        announce: report SPEAKING to the HUD while audio plays, then `then_state`.
        """
        clean = strip_markdown(text)
        if not clean:
            return True
        if not self.available:
            self.last_error = self._reason or UNAVAILABLE
            return False

        with self._speak_lock:
            stop = threading.Event()
            self._current_stop = stop
            chunks = split_for_speech(clean)
            rendered: "queue.Queue[tuple[str, bool] | Exception | None]" = queue.Queue()

            def _producer() -> None:
                for chunk in chunks:
                    if stop.is_set():
                        break
                    try:
                        item = self._render(chunk)
                    except Exception as exc:  # delivered to the consumer below
                        rendered.put(exc)
                        return
                    if stop.is_set():
                        _discard(item)
                        break
                    rendered.put(item)
                rendered.put(None)

            threading.Thread(target=_producer, name="clap-tts", daemon=True).start()
            started = False
            try:
                while True:
                    item = rendered.get()
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        raise item
                    try:
                        if stop.is_set():
                            break
                        if not started:
                            started = True
                            self._speaking.set()
                            if announce:
                                hub.set_state(AssistantState.SPEAKING)
                        self.player.play(item[0])
                    finally:
                        _discard(item)
                self.last_error = ""
                return True
            except TTSError as exc:
                log.error("TTS failed: %s", exc)
                self.last_error = exc.user_message
                hub.set_voice(self.status())
                return False
            except PlaybackError as exc:
                log.error("audio playback failed: %s", exc)
                self.last_error = UNAVAILABLE
                hub.set_voice(self.status())
                return False
            except Exception:
                log.exception("unexpected voice failure")
                self.last_error = UNAVAILABLE
                return False
            finally:
                stop.set()  # stops the producer if we left early
                while not rendered.empty():
                    leftover = rendered.get_nowait()
                    if isinstance(leftover, tuple):
                        _discard(leftover)
                if started:
                    self._tail_until = time.monotonic() + ECHO_TAIL_SECONDS
                self._speaking.clear()
                if started and announce and hub.state == AssistantState.SPEAKING:
                    hub.set_state(then_state, "")

    def speak_async(self, text: str, **kwargs) -> threading.Thread:
        t = threading.Thread(target=self.speak, args=(text,), kwargs=kwargs, daemon=True)
        t.start()
        return t

    def warm(self, phrases: list[str]) -> None:
        """Pre-synthesise short phrases into the cache (background)."""
        if not self.available:
            return

        def _run() -> None:
            for phrase in phrases:
                clean = strip_markdown(phrase)
                if self._cache_path(clean) is None:
                    continue
                try:
                    self._render(clean)
                except Exception as exc:
                    log.warning("could not pre-cache %r: %s", phrase, exc)
                    return

        threading.Thread(target=_run, name="clap-tts-warm", daemon=True).start()

    def stop(self) -> None:
        if self._current_stop is not None:
            self._current_stop.set()
        self.player.stop()


# ── Module-level service ──────────────────────────────────────────────────────

_service: "VoiceService | None" = None
_service_lock = threading.Lock()


def get_service() -> VoiceService:
    global _service
    with _service_lock:
        if _service is None:
            _service = VoiceService.from_config()
            hub.set_voice(_service.status())
            if _service.provider and not _service.provider.reference_voice:
                log.warning("Using %s — an approximation, not the CLAP reference voice.",
                            _service.provider.voice_label)
        return _service


def set_service(service: VoiceService) -> None:
    """Install a specific service (tests, alternative front-ends)."""
    global _service
    with _service_lock:
        _service = service
    hub.set_voice(service.status())


def running_on_macos() -> bool:
    return platform.system() == "Darwin"
