"""Test doubles: a scripted AI provider, a recording player, a fake TTS provider."""

from __future__ import annotations

import threading
import time

from ai.base import AIProvider, ModelTurn, ToolCall


def turn(text: str = "", *calls: ToolCall, finish: str = "stop") -> ModelTurn:
    return ModelTurn(text=text, tool_calls=list(calls), finish=finish)


def call(name: str, args: dict | None = None, id: str | None = None) -> ToolCall:
    return ToolCall(name=name, args=args or {}, id=id)


class ScriptedAI(AIProvider):
    """AIProvider double: each generate() returns (or raises) the next scripted item."""

    name = "scripted"

    def __init__(self, responses):
        super().__init__("test-model")
        self.responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, system, messages, tools):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RecordingPlayer:
    """AudioPlayer double: 'plays' by sleeping and records what was played."""

    available = True
    name = "recording"

    def __init__(self, seconds: float = 0.05):
        self.seconds = seconds
        self.played: list[bytes] = []
        self.playing = threading.Event()
        self.observed_speaking: list[bool] = []
        self.probe = None

    def play(self, path: str) -> None:
        with open(path, "rb") as fh:
            self.played.append(fh.read())
        self.playing.set()
        if self.probe:
            self.observed_speaking.append(self.probe())
        time.sleep(self.seconds)
        self.playing.clear()

    def stop(self) -> None:
        pass


class FakeProvider:
    name = "fake"
    audio_ext = "mp3"
    reference_voice = True
    voice_label = "fake voice"
    cache_key = "fake"

    def __init__(self, fail_with: Exception | None = None):
        self.calls: list[str] = []
        self.fail_with = fail_with

    def synthesize(self, text: str, out_path: str) -> None:
        self.calls.append(text)
        if self.fail_with:
            raise self.fail_with
        with open(out_path, "wb") as fh:
            fh.write(text.encode())
