"""
Audio playback for synthesised speech.

macOS: the native `afplay` (no extra dependencies, Apple Silicon native).
Elsewhere: the first available of ffplay, mpg123 or mpv.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import threading

_CANDIDATES = [
    ("afplay", []),
    ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ("mpg123", ["-q"]),
    ("mpv", ["--no-video", "--really-quiet"]),
]


class PlaybackError(RuntimeError):
    pass


class AudioPlayer:
    def __init__(self) -> None:
        self._command = self._find_player()
        self._proc: "subprocess.Popen | None" = None
        self._lock = threading.Lock()

    @staticmethod
    def _find_player() -> "list[str] | None":
        order = _CANDIDATES if platform.system() == "Darwin" else _CANDIDATES[1:]
        for name, args in order:
            path = shutil.which(name)
            if path:
                return [path, *args]
        return None

    @property
    def available(self) -> bool:
        return self._command is not None

    @property
    def name(self) -> str:
        return self._command[0].rsplit("/", 1)[-1] if self._command else "none"

    def play(self, path: str) -> None:
        """Play an audio file, blocking until it finishes or stop() is called."""
        if not self._command:
            raise PlaybackError("No audio player found (afplay on macOS; ffplay/mpg123/mpv elsewhere)")
        with self._lock:
            self._proc = subprocess.Popen(
                [*self._command, path], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
        proc = self._proc
        _, stderr = proc.communicate()
        with self._lock:
            self._proc = None
        if proc.returncode not in (0, -15, -9):  # -15/-9: stopped on purpose
            raise PlaybackError(f"{self.name} exited with {proc.returncode}: {stderr.decode(errors='ignore').strip()[:200]}")

    def stop(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
