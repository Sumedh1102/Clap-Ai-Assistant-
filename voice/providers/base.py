"""Provider interface for CLAP's voice output."""

from __future__ import annotations

from abc import ABC, abstractmethod


class TTSError(RuntimeError):
    """Synthesis failed. `user_message` is short and safe to show in the HUD."""

    def __init__(self, user_message: str, detail: str = "") -> None:
        super().__init__(f"{user_message} ({detail})" if detail else user_message)
        self.user_message = user_message
        self.detail = detail


class TTSProvider(ABC):
    #: short identifier, e.g. "elevenlabs"
    name: str = ""
    #: file extension of the synthesised audio, e.g. "mp3"
    audio_ext: str = "mp3"
    #: True when the voice is the CLAP reference voice (not an approximation)
    reference_voice: bool = False

    @property
    @abstractmethod
    def voice_label(self) -> str:
        """Human-readable voice description for status displays."""

    @property
    def cache_key(self) -> str:
        """Identifies the voice configuration; cached audio is keyed by it."""
        return f"{self.name}:{self.voice_label}"

    @abstractmethod
    def synthesize(self, text: str, out_path: str) -> None:
        """Write speech audio for `text` to `out_path`. Raise TTSError on failure."""
