"""
Voice input — single persistent microphone stream.

ONE sounddevice.InputStream stays open for the entire session:
  - No open/close cycling → no blinking mic indicator
  - LISTENING state: overlapping 2.5 s windows scanned for the wake word "CLAP"
  - RECORDING state: captures command audio until silence detected
  - While CLAP itself is speaking, microphone frames are ignored so CLAP
    never wakes itself or transcribes its own voice.

Public API:
  wake_word_available() → bool
  wake_word_in(text)    → bool
  transcribe(audio)     → str          (used by push-to-talk fallback)
  run_voice_loop(on_command, on_wake, stop_event, ...)
"""

from __future__ import annotations

import collections
import queue
import re
import threading
from typing import Callable

import numpy as np

try:
    import sounddevice as sd
    _SD_OK = True
except Exception:
    _SD_OK = False

try:
    from faster_whisper import WhisperModel
    _WHISPER_OK = True
except ImportError:
    _WHISPER_OK = False

_whisper: "WhisperModel | None" = None
SR = 16_000
BLOCKSIZE = 512   # ~32 ms per callback frame

# Wake word "CLAP" — also matches "hey clap", "Hey, CLAP.", "C.L.A.P." and
# common Whisper spellings. Whole words only: "clapping"/"claps" do not match.
_WAKE_RE = re.compile(r"\b(?:clap|clapp|klap|c l a p)\b")
# Whisper annotates non-speech sounds as "(clapping)", "[APPLAUSE]", "*claps*".
_ANNOTATION_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]|\*[^*]*\*|♪[^♪]*♪")


def _get_whisper() -> "WhisperModel":
    global _whisper
    if _whisper is None:
        _whisper = WhisperModel("base.en", device="cpu", compute_type="int8")
    return _whisper


def wake_word_in(text: str) -> bool:
    t = _ANNOTATION_RE.sub(" ", text.lower())
    t = re.sub(r"(?<=\b[a-z])[.\-](?=[a-z]\b)", " ", t)   # c.l.a.p / c-l-a-p → c l a p
    t = t.replace(".", " ")
    return bool(_WAKE_RE.search(t))


_wake_in = wake_word_in  # backwards-compatible name


def wake_word_available() -> bool:
    return _SD_OK and _WHISPER_OK


def transcribe(audio: np.ndarray) -> str:
    """Transcribe float32 16 kHz mono audio. Used by push-to-talk fallback."""
    segs, _ = _get_whisper().transcribe(
        audio, beam_size=5, language="en", vad_filter=True
    )
    return " ".join(s.text.strip() for s in segs).strip()


# ── Unified voice loop ────────────────────────────────────────────────────────

def run_voice_loop(
    on_command: Callable[[str], None],
    on_wake: "Callable[[], None] | None" = None,
    stop_event: "threading.Event | None" = None,
    on_capture_start: "Callable[[], None] | None" = None,
    on_transcribing: "Callable[[], None] | None" = None,
    on_no_speech: "Callable[[], None] | None" = None,
    is_output_active: "Callable[[], bool] | None" = None,
    on_ready: "Callable[[], None] | None" = None,
) -> None:
    """
    Open ONE InputStream and run a state machine:

      LISTENING → scan overlapping 2.5 s windows every 0.5 s for "CLAP"
      RECORDING → accumulate audio until 1.5 s of silence (max 30 s)
                  then transcribe and call on_command(text)

    Optional hooks report real activity to the HUD:
      on_capture_start  first command audio frame recorded
      on_transcribing   recording finished, Whisper running
      on_no_speech      recording contained no speech
      on_ready          microphone stream open, wake word armed
    is_output_active() → True while CLAP is speaking; frames are then ignored.

    Blocks until stop_event is set.
    """
    if not _SD_OK:
        raise RuntimeError("sounddevice not installed")
    if not _WHISPER_OK:
        raise RuntimeError("faster-whisper not installed")

    # ── Tuning constants ─────────────────────────────────────────────────
    ENERGY_MIN     = 0.005   # skip silent chunks during wake scan
    SILENCE_THRESH = 0.012   # RMS below this counts as silence while recording
    SILENCE_BLOCKS = int(1.5 * SR / BLOCKSIZE)   # ~47 blocks = 1.5 s
    MIN_REC_BLOCKS = int(0.4 * SR / BLOCKSIZE)   # ~12 blocks = 0.4 s min recording
    MAX_REC_BLOCKS = int(30  * SR / BLOCKSIZE)   # ~937 blocks = 30 s max
    WAKE_WIN       = int(2.5 * SR)               # 40 000 samples
    CHECK_EVERY    = int(0.5 * SR / BLOCKSIZE)   # check wake every 0.5 s of frames

    stop = stop_event or threading.Event()
    frame_q: "queue.Queue[np.ndarray]" = queue.Queue()

    def _cb(indata, frames, _t, _s):
        frame_q.put(indata[:, 0].copy())

    # Warm up Whisper before opening the stream
    _get_whisper()

    def _consumer() -> None:
        from enum import Enum

        class Mode(Enum):
            LISTENING = 0
            RECORDING = 1

        mode            = Mode.LISTENING
        rolling         = collections.deque(maxlen=WAKE_WIN)
        frames_to_check = CHECK_EVERY   # countdown until next wake scan
        rec_buf: list[np.ndarray] = []
        silent_streak   = 0

        while not stop.is_set():
            try:
                frame = frame_q.get(timeout=0.5)
            except queue.Empty:
                continue

            if is_output_active and is_output_active():
                # CLAP is talking: never hear ourselves (no self-wake, no echo in commands)
                if mode == Mode.LISTENING:
                    rolling.clear()
                    frames_to_check = CHECK_EVERY
                continue

            if mode == Mode.LISTENING:
                rolling.extend(frame)
                frames_to_check -= 1

                if frames_to_check <= 0:
                    frames_to_check = CHECK_EVERY
                    if len(rolling) < WAKE_WIN:
                        continue
                    chunk = np.array(rolling, dtype="float32")
                    if float(np.sqrt(np.mean(chunk ** 2))) < ENERGY_MIN:
                        continue

                    segs, _ = _get_whisper().transcribe(
                        chunk, beam_size=3, language="en", vad_filter=False
                    )
                    text = " ".join(s.text.strip() for s in segs).strip()

                    if wake_word_in(text):
                        mode = Mode.RECORDING
                        rec_buf = []
                        silent_streak = 0
                        rolling.clear()
                        if on_wake:
                            threading.Thread(target=on_wake, daemon=True).start()

            elif mode == Mode.RECORDING:
                if not rec_buf and on_capture_start:
                    on_capture_start()
                rec_buf.append(frame)
                rms = float(np.sqrt(np.mean(frame ** 2)))

                if rms < SILENCE_THRESH:
                    silent_streak += 1
                else:
                    silent_streak = 0

                done = (
                    silent_streak >= SILENCE_BLOCKS and len(rec_buf) >= MIN_REC_BLOCKS
                ) or len(rec_buf) >= MAX_REC_BLOCKS

                if done:
                    audio = np.concatenate(rec_buf).astype("float32")
                    rec_buf = []
                    silent_streak = 0
                    mode = Mode.LISTENING

                    if on_transcribing:
                        on_transcribing()
                    segs, _ = _get_whisper().transcribe(
                        audio, beam_size=5, language="en", vad_filter=True
                    )
                    text = " ".join(s.text.strip() for s in segs).strip()
                    if text:
                        threading.Thread(
                            target=on_command, args=(text,), daemon=True
                        ).start()
                    elif on_no_speech:
                        on_no_speech()

    threading.Thread(target=_consumer, daemon=True, name="clap-voice-consumer").start()

    with sd.InputStream(
        samplerate=SR, channels=1, dtype="float32",
        blocksize=BLOCKSIZE, callback=_cb,
    ):
        if on_ready:
            on_ready()
        stop.wait()


# ── Push-to-talk helpers (used when wake word unavailable) ────────────────────

def record_until_silence(
    silence_threshold: float = 0.015,
    silence_seconds: float = 1.5,
    max_seconds: float = 30.0,
    min_seconds: float = 0.4,
) -> np.ndarray:
    if not _SD_OK:
        raise RuntimeError("sounddevice not installed")

    chunk_n  = BLOCKSIZE
    sil_lim  = int(silence_seconds * SR / chunk_n)
    min_ch   = int(min_seconds    * SR / chunk_n)
    max_ch   = int(max_seconds    * SR / chunk_n)
    chunks: list[np.ndarray] = []
    streak   = 0

    with sd.InputStream(samplerate=SR, channels=1, dtype="float32") as s:
        for _ in range(max_ch):
            frame, _ = s.read(chunk_n)
            chunk = frame[:, 0]
            chunks.append(chunk)
            if float(np.sqrt(np.mean(chunk ** 2))) < silence_threshold and len(chunks) > min_ch:
                streak += 1
                if streak >= sil_lim:
                    break
            else:
                streak = 0

    return np.concatenate(chunks) if chunks else np.zeros(chunk_n, dtype="float32")
