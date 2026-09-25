"""Session pipeline: every HUD state comes from a real transition, in order."""

import queue
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests import _env  # noqa: F401
from tests.fakes import FakeProvider, RecordingPlayer

import agent
import voice
from events import AssistantState, hub
from session import ClapSession
from voice.providers.base import TTSError
from voice.service import VoiceService


def drain(q: "queue.Queue") -> list[dict]:
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


def states(events: list[dict]) -> list[str]:
    return [e["state"] for e in events if e["type"] == "state"]


def fake_chat_with_tool(ok: bool):
    def _chat(text, history, on_tool_call=None, on_tool_result=None, voice_mode=False):
        on_tool_call("open_application", {"app_name": "Spotify"})
        result = {"success": True} if ok else {"success": False, "error": "Spotify could not be opened"}
        on_tool_result("open_application", {"app_name": "Spotify"}, result)
        reply = "Opening Spotify." if ok else "Spotify could not be opened."
        return reply, history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
    return _chat


class SessionStateTest(unittest.TestCase):
    def setUp(self):
        hub.set_state(AssistantState.STANDBY)
        self.q = hub.subscribe()

    def tearDown(self):
        hub.unsubscribe(self.q)

    def test_tool_turn_state_sequence_and_activity(self):
        with mock.patch.object(agent, "chat", fake_chat_with_tool(ok=True)):
            result = ClapSession().handle("Open Spotify.", source="web")
        events = drain(self.q)
        self.assertTrue(result.ok)
        self.assertEqual(result.reply, "Opening Spotify.")
        self.assertEqual(states(events), ["thinking", "executing", "thinking", "standby"])
        executing = next(e for e in events if e["type"] == "state" and e["state"] == "executing")
        self.assertEqual(executing["detail"], "Opening Spotify")
        acts = [e for e in events if e["type"] == "activity"]
        self.assertEqual([a["status"] for a in acts], ["running", "completed"])
        self.assertEqual(acts[0]["label"], "macOS App Control")
        roles = [e["role"] for e in events if e["type"] == "message"]
        self.assertEqual(roles, ["user", "assistant"])

    def test_failed_tool_marks_activity_failed(self):
        with mock.patch.object(agent, "chat", fake_chat_with_tool(ok=False)):
            result = ClapSession().handle("Open Spotify.")
        acts = [e for e in drain(self.q) if e["type"] == "activity"]
        self.assertEqual(acts[-1]["status"], "failed")
        self.assertIn("could not be opened", acts[-1]["error"])
        self.assertEqual(result.reply, "Spotify could not be opened.")

    def test_ai_unreachable_enters_error_state(self):
        def boom(*a, **k):
            raise agent.ClapAIError("CLAP cannot reach the AI service.")
        with mock.patch.object(agent, "chat", boom):
            result = ClapSession().handle("hello")
        events = drain(self.q)
        self.assertFalse(result.ok)
        self.assertEqual(states(events)[-1], "error")
        self.assertIn({"type": "error", "message": "CLAP cannot reach the AI service."},
                      [{k: e[k] for k in ("type", "message")} for e in events if e["type"] == "error"])
        self.assertEqual(hub.snapshot()["error"], "CLAP cannot reach the AI service.")

    def test_unexpected_exception_is_not_leaked(self):
        with mock.patch.object(agent, "chat", side_effect=KeyError("secret internals")):
            result = ClapSession().handle("hello")
        self.assertNotIn("secret internals", result.error)
        self.assertIn("internal error", result.error)

    def test_busy_session_rejects_second_voice_command(self):
        started, release = threading.Event(), threading.Event()

        def slow_chat(text, history, **kw):
            started.set()
            release.wait(5)
            return "done", history

        session = ClapSession()
        with mock.patch.object(agent, "chat", slow_chat):
            t = threading.Thread(target=session.handle, args=("first",))
            t.start()
            started.wait(5)
            second = session.handle("second", source="voice", wait=False)
            release.set()
            t.join(5)
        self.assertFalse(second.ok)
        self.assertIn("still working", second.error)


class SpokenReplyTest(unittest.TestCase):
    def setUp(self):
        hub.set_state(AssistantState.STANDBY)
        self.q = hub.subscribe()

    def tearDown(self):
        hub.unsubscribe(self.q)

    def test_speaking_state_only_while_audio_plays(self):
        player = RecordingPlayer(seconds=0.1)
        service = VoiceService(FakeProvider(), player=player, cache_dir=Path(_env.TMP) / "tts")
        player.probe = lambda: hub.state == AssistantState.SPEAKING
        voice.set_service(service)
        with mock.patch.object(agent, "chat", lambda t, h, **k: ("Opening Spotify.", h)):
            result = ClapSession(speak_replies=True).handle("Open Spotify.")
        self.assertTrue(result.spoken)
        self.assertEqual(player.observed_speaking, [True])  # SPEAKING while playing
        self.assertEqual(states(drain(self.q)), ["thinking", "speaking", "standby"])
        self.assertFalse(service._speaking.is_set())  # playback flag cleared when audio ends

    def test_tts_failure_reports_voice_unavailable(self):
        provider = FakeProvider(fail_with=TTSError("Voice output is currently unavailable.", "HTTP 500"))
        voice.set_service(VoiceService(provider, player=RecordingPlayer(), cache_dir=Path(_env.TMP) / "tts"))
        with mock.patch.object(agent, "chat", lambda t, h, **k: ("Hello.", h)):
            result = ClapSession(speak_replies=True).handle("hi")
        self.assertTrue(result.ok)          # the reply itself succeeded (shown in HUD)
        self.assertFalse(result.spoken)
        self.assertEqual(hub.snapshot()["error"], "Voice output is currently unavailable.")
        self.assertEqual(states(drain(self.q))[-1], "error")


if __name__ == "__main__":
    unittest.main()
