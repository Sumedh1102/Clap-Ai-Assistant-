"""
Provider-neutral AI interface for CLAP.

The agent loop (agent.py) talks only to AIProvider and these neutral types; a
provider module (e.g. ai/gemini.py) translates them to and from its SDK. To add
another model provider, implement AIProvider — nothing else in CLAP changes.

Neutral conversation messages (what the agent keeps in history):

    {"role": "user", "content": "Open Spotify"}
    {"role": "assistant", "content": "Opening Spotify.",
     "tool_calls": [ToolCall, ...],        # when the model requested tools
     "raw": <provider object>}              # optional, in-memory only
    {"role": "tool", "results": [{"id", "name", "content": dict, "is_error": bool}]}

Tool specs are plain JSON Schema: {"name", "description", "parameters"}.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ClapAIError(RuntimeError):
    """The AI service could not produce a reply. `user_message` is safe to show/speak."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


@dataclass
class ToolCall:
    name: str
    args: dict
    id: str | None = None


@dataclass
class ModelTurn:
    """One model response.

    finish: "stop" | "max_tokens" | "blocked" | "malformed" | "empty"
    raw:    provider-native content, kept so the provider can replay the turn
            exactly (e.g. Gemini thought signatures on function calls).
    """

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish: str = "stop"
    raw: Any = None


class AIProvider(ABC):
    #: provider identifier, e.g. "gemini"
    name: str = ""

    def __init__(self, model: str) -> None:
        self.model = model

    @abstractmethod
    def generate(self, system: str, messages: list[dict], tools: list[dict]) -> ModelTurn:
        """
        Run one model call over the neutral conversation. Raise ClapAIError
        (with a user-facing message) when the service cannot answer.
        """
