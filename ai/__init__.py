"""
CLAP's AI layer.

    from ai import get_provider
    turn = get_provider().generate(system, messages, tools)

The active provider is Google Gemini (ai/gemini.py). Everything outside this
package uses the neutral interface in ai/base.py, so another provider can be
added without touching the agent, the HUD, voice or tools.
"""

from __future__ import annotations

import threading

from ai.base import AIProvider, ClapAIError, ModelTurn, ToolCall

_provider: AIProvider | None = None
_lock = threading.Lock()


def get_provider() -> AIProvider:
    """The shared provider instance (one reusable SDK client per process)."""
    global _provider
    with _lock:
        if _provider is None:
            from config import config
            from ai.gemini import GeminiProvider
            _provider = GeminiProvider(api_key=config.GEMINI_API_KEY, model=config.MODEL)
        return _provider


def set_provider(provider: AIProvider | None) -> None:
    """Install a specific provider (tests), or None to rebuild from config."""
    global _provider
    with _lock:
        _provider = provider


__all__ = ["AIProvider", "ClapAIError", "ModelTurn", "ToolCall", "get_provider", "set_provider"]
