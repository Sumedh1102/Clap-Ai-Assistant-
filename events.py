"""
CLAP event hub — the single source of truth for what the assistant is doing.

Everything that changes CLAP's observable state (microphone capture, Claude
calls, tool execution, speech playback, errors) reports here. Subscribers
(the web HUD via server-sent events, the floating overlay) receive the same
events, so every surface reflects real application activity.

Thread-safe: producers run on the voice, web and scheduler threads.
"""

from __future__ import annotations

import collections
import itertools
import logging
import queue
import threading
import time
from enum import Enum
from typing import Callable

log = logging.getLogger("clap.events")


class AssistantState(str, Enum):
    STANDBY = "standby"
    LISTENING = "listening"
    THINKING = "thinking"
    EXECUTING = "executing"
    SPEAKING = "speaking"
    ERROR = "error"


class EventHub:
    def __init__(self, message_log: int = 60, activity_log: int = 30) -> None:
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._subscribers: list[queue.Queue] = []
        self._listeners: list[Callable[[dict], None]] = []
        self._messages: collections.deque[dict] = collections.deque(maxlen=message_log)
        self._activities: collections.deque[dict] = collections.deque(maxlen=activity_log)
        self._state = AssistantState.STANDBY
        self._detail = ""
        self._error = ""
        self._mic = "off"          # off | armed | capturing | unavailable
        self._voice: dict = {"available": False, "provider": None, "voice": None, "reason": "not initialised"}
        self._mode = ""
        self._started_at = time.time()

    # ── Subscription ──────────────────────────────────────────────────────

    def subscribe(self) -> "queue.Queue[dict]":
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[dict]") -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def add_listener(self, callback: Callable[[dict], None]) -> None:
        """In-process listener, called synchronously — must not block."""
        with self._lock:
            self._listeners.append(callback)

    def _publish(self, event: dict) -> None:
        event.setdefault("ts", time.time())
        with self._lock:
            subscribers = list(self._subscribers)
            listeners = list(self._listeners)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # slow client — it will resync from the next snapshot
        for cb in listeners:
            try:
                cb(event)
            except Exception:
                log.exception("event listener failed")

    # ── State ─────────────────────────────────────────────────────────────

    @property
    def state(self) -> AssistantState:
        return self._state

    def set_state(self, state: AssistantState, detail: str = "") -> None:
        with self._lock:
            if state == self._state and detail == self._detail:
                return
            self._state = state
            self._detail = detail
            if state != AssistantState.ERROR:
                self._error = ""
        self._publish({"type": "state", "state": state.value, "detail": detail})

    def set_error(self, message: str) -> None:
        """Enter the ERROR state with a user-facing message (no stack traces)."""
        with self._lock:
            self._state = AssistantState.ERROR
            self._detail = message
            self._error = message
        self._publish({"type": "state", "state": AssistantState.ERROR.value, "detail": message})
        self._publish({"type": "error", "message": message})

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self._mode = mode

    def set_mic(self, status: str) -> None:
        with self._lock:
            if status == self._mic:
                return
            self._mic = status
        self._publish({"type": "mic", "status": status})

    def set_voice(self, info: dict) -> None:
        with self._lock:
            self._voice = dict(info)
        self._publish({"type": "voice", **info})

    # ── Conversation & activity ───────────────────────────────────────────

    def add_message(self, role: str, text: str, source: str = "") -> int:
        msg = {"id": next(self._ids), "role": role, "text": text, "source": source, "ts": time.time()}
        with self._lock:
            self._messages.append(msg)
        self._publish({"type": "message", **msg})
        return msg["id"]

    def activity_start(self, tool: str, label: str, action: str) -> int:
        act = {
            "id": next(self._ids), "tool": tool, "label": label, "action": action,
            "status": "running", "error": "", "ts": time.time(), "ended": None,
        }
        with self._lock:
            self._activities.append(act)
        self._publish({"type": "activity", **act})
        return act["id"]

    def activity_end(self, activity_id: int, ok: bool, error: str = "") -> None:
        with self._lock:
            act = next((a for a in self._activities if a["id"] == activity_id), None)
            if act is None:
                return
            act["status"] = "completed" if ok else "failed"
            act["error"] = error
            act["ended"] = time.time()
            payload = dict(act)
        self._publish({"type": "activity", **payload})

    def notice(self, message: str) -> None:
        """Non-error informational message for the HUD (e.g. 'still busy')."""
        self._publish({"type": "notice", "message": message})

    # ── Snapshot ──────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "type": "snapshot",
                "state": self._state.value,
                "detail": self._detail,
                "error": self._error,
                "mic": self._mic,
                "voice": dict(self._voice),
                "mode": self._mode,
                "messages": list(self._messages),
                "activities": [dict(a) for a in self._activities],
                "started_at": self._started_at,
                "ts": time.time(),
            }


hub = EventHub()
