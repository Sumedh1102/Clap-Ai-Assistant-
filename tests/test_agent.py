"""Agent loop: tool calling, honest failures, persistence, error mapping, history trimming."""

import json
import unittest
from unittest import mock

from tests import _env  # noqa: F401  (isolated DB + key)
from tests.fakes import FakeClient, message, request, status_response, text, tool_use

import anthropic

import agent
from database import clear_history, load_recent_history


class AgentLoopTest(unittest.TestCase):
    def setUp(self):
        clear_history()

    def run_chat(self, responses, handlers=None, **kwargs):
        client = FakeClient(responses)
        patches = [mock.patch.object(agent, "_get_client", return_value=client)]
        for name, fn in (handlers or {}).items():
            patches.append(mock.patch.dict(agent.TOOL_HANDLERS, {name: fn}))
        for p in patches:
            p.start()
        try:
            reply, history = agent.chat("Open Spotify.", [], **kwargs)
        finally:
            for p in patches:
                p.stop()
        return reply, history, client

    def test_tool_call_success_round_trip(self):
        calls, results = [], []
        opened = mock.Mock(return_value={"success": True, "message": "Opened Spotify"})
        reply, history, client = self.run_chat(
            [
                message("tool_use", tool_use("open_application", {"app_name": "Spotify"}, "toolu_A")),
                message("end_turn", text("Opening Spotify.")),
            ],
            handlers={"open_application": opened},
            on_tool_call=lambda n, i: calls.append((n, i)),
            on_tool_result=lambda n, i, r: results.append(r),
        )
        self.assertEqual(reply, "Opening Spotify.")
        opened.assert_called_once_with(app_name="Spotify")
        self.assertEqual(calls, [("open_application", {"app_name": "Spotify"})])
        self.assertEqual(results, [{"success": True, "message": "Opened Spotify"}])

        second = client.messages.calls[1]["messages"]
        tool_result = second[-1]["content"][0]
        self.assertEqual(tool_result["tool_use_id"], "toolu_A")
        self.assertNotIn("is_error", tool_result)
        self.assertIn("CLAP", client.messages.calls[0]["system"])
        self.assertNotIn("JARVIS", client.messages.calls[0]["system"])

        # Persistence works (the pre-CLAP code crashed serialising SDK blocks here)
        stored = load_recent_history(10)
        self.assertEqual(stored[-1], {"role": "assistant", "content": [{"type": "text", "text": "Opening Spotify."}]})
        self.assertEqual(stored[-2], {"role": "user", "content": "Open Spotify."})

    def test_failed_tool_is_flagged_as_error(self):
        failing = mock.Mock(return_value={"success": False, "error": "Spotify could not be opened: application not found"})
        reply, _, client = self.run_chat(
            [
                message("tool_use", tool_use("open_application", {"app_name": "Spotify"})),
                message("end_turn", text("Spotify could not be opened.")),
            ],
            handlers={"open_application": failing},
        )
        tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
        self.assertTrue(tool_result["is_error"])
        self.assertIn("could not be opened", json.loads(tool_result["content"])["error"])
        self.assertEqual(reply, "Spotify could not be opened.")

    def test_tool_exception_becomes_error_result(self):
        boom = mock.Mock(side_effect=RuntimeError("disk on fire"))
        _, _, client = self.run_chat(
            [message("tool_use", tool_use("add_task", {"title": "x"})), message("end_turn", text("That failed."))],
            handlers={"add_task": boom},
        )
        tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
        self.assertTrue(tool_result["is_error"])
        self.assertIn("disk on fire", tool_result["content"])

    def test_voice_mode_prompt(self):
        _, _, client = self.run_chat([message("end_turn", text("Done."))], voice_mode=True)
        self.assertIn("VOICE MODE ACTIVE", client.messages.calls[0]["system"])

    def test_api_errors_map_to_user_messages(self):
        cases = [
            (anthropic.APIConnectionError(request=request()), "CLAP cannot reach the AI service."),
            (anthropic.APITimeoutError(request=request()), "CLAP cannot reach the AI service."),
            (anthropic.AuthenticationError("bad key", response=status_response(401), body=None), "API key was rejected"),
            (anthropic.RateLimitError("slow down", response=status_response(429), body=None), "rate limiting"),
            (anthropic.InternalServerError("oops", response=status_response(500), body=None), "temporarily unavailable"),
            (anthropic.NotFoundError("no model", response=status_response(404), body=None), "was not found"),
        ]
        for exc, expected in cases:
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaises(agent.ClapAIError) as ctx:
                    self.run_chat([exc])
                self.assertIn(expected, ctx.exception.user_message)
                self.assertNotIn("Traceback", ctx.exception.user_message)

    def test_unknown_tool(self):
        self.assertEqual(agent.run_tool("nope", {})["success"], False)


class TrimHistoryTest(unittest.TestCase):
    def test_trim_never_starts_with_orphaned_tool_result(self):
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": [tool_use("list_tasks", {})]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "{}"}]},
            {"role": "assistant", "content": [text("ok")]},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": [{"type": "text", "text": "fine"}]},
        ]
        trimmed = agent.trim_history(history, 4)
        self.assertEqual(trimmed[0], {"role": "user", "content": "second"})

    def test_trim_drops_leading_assistant(self):
        history = [{"role": "assistant", "content": "x"}, {"role": "user", "content": "y"}]
        self.assertEqual(agent.trim_history(history, 10), [{"role": "user", "content": "y"}])


if __name__ == "__main__":
    unittest.main()
