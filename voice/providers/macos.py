"""
macOS `say` provider — an explicit, opt-in local approximation.

This is NOT the CLAP reference voice. It is only used when the user sets
CLAP_TTS_PROVIDER=macos (for example, to work offline). CLAP_TTS_VOICE_ID
selects the macOS voice (e.g. "Ava (Premium)"); empty uses the system voice.
The rate approximates the reference recording's unhurried pace.
"""

from __future__ import annotations

import platform
import shutil
import subprocess

from voice.providers.base import TTSError, TTSProvider

# The reference voice speaks at roughly 3 syllables/second; macOS default is ~175-200 wpm.
DEFAULT_RATE = 165


class MacOSSayProvider(TTSProvider):
    name = "macos"
    audio_ext = "aiff"
    reference_voice = False

    def __init__(self, voice: str = "", rate: int = DEFAULT_RATE) -> None:
        if platform.system() != "Darwin" or not shutil.which("say"):
            raise ValueError("the macOS provider requires macOS and the `say` command")
        self.voice = voice
        self.rate = rate

    @property
    def voice_label(self) -> str:
        return f"macOS say ({self.voice or 'system voice'})"

    def synthesize(self, text: str, out_path: str) -> None:
        cmd = ["say", "-r", str(self.rate), "-o", out_path]
        if self.voice:
            cmd += ["-v", self.voice]
        result = subprocess.run([*cmd, text], capture_output=True, text=True)
        if result.returncode != 0:
            raise TTSError("Voice output is currently unavailable.", f"say failed: {result.stderr.strip()[:200]}")
