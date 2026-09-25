"""
CLAP voice output.

    from voice import speak, speak_async
    speak("Hello. I am CLAP.")

Provider selection, caching, playback and HUD state live in voice/service.py.
"""

from __future__ import annotations

from voice.service import UNAVAILABLE, VoiceService, get_service, set_service


def speak(text: str, **kwargs) -> bool:
    """Speak text (blocking). Returns False if voice output is unavailable or failed."""
    return get_service().speak(text, **kwargs)


def speak_async(text: str, **kwargs):
    """Speak text in a background thread — returns immediately."""
    return get_service().speak_async(text, **kwargs)


def stop() -> None:
    get_service().stop()


def is_speaking() -> bool:
    return get_service().is_speaking()


def status() -> dict:
    return get_service().status()


__all__ = [
    "UNAVAILABLE", "VoiceService", "get_service", "set_service",
    "speak", "speak_async", "stop", "is_speaking", "status",
]
