"""
CLAP session — one conversation shared by every input (voice, web HUD, scheduler).

handle(text) runs the full pipeline and reports each real transition to the
event hub:

    user message → THINKING → (EXECUTING ⇄ THINKING per tool) → reply
                 → SPEAKING while audio plays → STANDBY
    any failure  → ERROR with a short user-facing message
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from config import config
from database import load_recent_history
from events import AssistantState, hub
from tools.labels import describe_tool_call, tool_failed

log = logging.getLogger("clap.session")

BUSY_MESSAGE = "CLAP is still working on the previous request."
INTERNAL_ERROR = "CLAP hit an internal error. Details are in logs/clap.log."


@dataclass
class TurnResult:
    ok: bool
    reply: str = ""
    error: str = ""
    message_id: int | None = None
    spoken: bool = False


class ClapSession:
    def __init__(self, speak_replies: bool = False, voice_mode: bool = False) -> None:
        """
        speak_replies: speak every reply through the voice service.
        voice_mode:    ask Claude for short, speakable replies.
        """
        self.speak_replies = speak_replies
        self.voice_mode = voice_mode
        self._lock = threading.Lock()
        self._history: list[dict] = load_recent_history(config.HISTORY_LIMIT)
        self._activity_id: int | None = None

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def reset_history(self) -> None:
        with self._lock:
            self._history = []

    # ── Tool callbacks (called from agent.chat) ───────────────────────────

    def _on_tool_call(self, name: str, inputs: dict) -> None:
        label, action = describe_tool_call(name, inputs)
        self._activity_id = hub.activity_start(name, label, action)
        hub.set_state(AssistantState.EXECUTING, action)

    def _on_tool_result(self, name: str, inputs: dict, result: dict) -> None:
        failure = tool_failed(result)
        if self._activity_id is not None:
            hub.activity_end(self._activity_id, ok=failure is None, error=failure or "")
            self._activity_id = None
        hub.set_state(AssistantState.THINKING)

    # ── Pipeline ──────────────────────────────────────────────────────────

    def handle(self, text: str, source: str = "web", wait: bool = True, timeout: float = 180.0) -> TurnResult:
        text = (text or "").strip()
        if not text:
            return TurnResult(ok=False, error="Empty command")

        acquired = self._lock.acquire(timeout=timeout) if wait else self._lock.acquire(blocking=False)
        if not acquired:
            hub.notice(BUSY_MESSAGE)
            return TurnResult(ok=False, error=BUSY_MESSAGE)
        try:
            return self._run(text, source)
        finally:
            self._lock.release()

    def _run(self, text: str, source: str) -> TurnResult:
        from agent import ClapAIError, chat

        hub.add_message("user", text, source)
        hub.set_state(AssistantState.THINKING)
        try:
            reply, self._history = chat(
                text,
                self._history,
                on_tool_call=self._on_tool_call,
                on_tool_result=self._on_tool_result,
                voice_mode=self.voice_mode,
            )
        except ClapAIError as exc:
            return self._fail(exc.user_message, source)
        except Exception:
            log.exception("command failed: %r", text)
            return self._fail(INTERNAL_ERROR, source)
        finally:
            if self._activity_id is not None:  # tool interrupted by an exception
                hub.activity_end(self._activity_id, ok=False, error="Interrupted")
                self._activity_id = None

        message_id = hub.add_message("assistant", reply, source) if reply else None
        spoken = False
        if self.speak_replies and reply:
            import voice
            spoken = voice.speak(reply)
            if not spoken:
                hub.set_error(voice.get_service().last_error or voice.UNAVAILABLE)
                return TurnResult(ok=True, reply=reply, message_id=message_id, spoken=False,
                                  error=voice.get_service().last_error)
        hub.set_state(AssistantState.STANDBY)
        return TurnResult(ok=True, reply=reply, message_id=message_id, spoken=spoken)

    def _fail(self, message: str, source: str) -> TurnResult:
        hub.set_error(message)
        message_id = hub.add_message("system", message, source)
        if self.speak_replies:
            import voice
            # Speak the error but keep the HUD in the ERROR state.
            voice.speak(message, announce=False)
        return TurnResult(ok=False, error=message, message_id=message_id)
