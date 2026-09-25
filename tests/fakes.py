"""Test doubles: scripted Claude responses, a recording player, a fake TTS provider."""

from __future__ import annotations

import threading
import time

import httpx
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage


def message(stop_reason: str, *blocks) -> Message:
    return Message.model_construct(
        id="msg_test", type="message", role="assistant", model="test-model",
        content=list(blocks), stop_reason=stop_reason, stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def text(t: str) -> TextBlock:
    return TextBlock(type="text", text=t)


def tool_use(name: str, inputs: dict, id: str = "toolu_1") -> ToolUseBlock:
    return ToolUseBlock(type="tool_use", id=id, name=name, input=inputs)


class ScriptedMessages:
    """Stands in for client.messages; each create() pops the next scripted response."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        # Snapshot the messages list: the agent keeps appending to the same list.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(kwargs) if callable(item) else item


class FakeClient:
    def __init__(self, responses):
        self.messages = ScriptedMessages(responses)


def request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def status_response(code: int) -> httpx.Response:
    return httpx.Response(code, request=request())


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
