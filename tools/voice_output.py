"""
Compatibility shim — CLAP's voice output lives in the voice/ package.

Kept so existing imports (`from tools.voice_output import speak`) keep working.
"""

from voice import speak, speak_async  # noqa: F401
from voice.text import strip_markdown as _strip_markdown  # noqa: F401
