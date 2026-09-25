"""Agent loop (provider-neutral): tool calling, honest failures, persistence, history."""

import unittest
from unittest import mock

from tests import _env  # noqa: F401  (isolated DB + key)
from tests.fakes import ScriptedAI, call, turn

import agent
import ai
from database import clear_history, load_recent_history, save_message


class AgentLoopTest(unittest.TestCase):
    def setUp(self):
        clear_history()

    def tearDown(self):
        ai.set_provider(None)

    def run_chat(self, responses, handlers=None, message="Open Spotify.", history=None, **kwargs):
        provider = ScriptedAI(responses)
        ai.set_provider(provider)
        with mock.patch.dict(agent.TOOL_HANDLERS, handlers or {}):
            reply, new_history = agent.chat(message, history or [], **kwargs)
        return reply, new_history, provider

    def test_tool_call_success_round_trip(self):
        calls, results = [], []
        opened = mock.Mock(return_value={"success": True, "message": "Opened Spotify"})
        reply, history, provider = self.run_chat(
            [turn("", call("open_application", {"app_name": "Spotify"}, "c1")), turn("Opening Spotify.")],
            handlers={"open_application": opened},
            on_tool_call=lambda n, i: calls.append((n, i)),
            on_tool_result=lambda n, i, r: results.append(r),
        )
        self.assertEqual(reply, "Opening Spotify.")
        opened.assert_called_once_with(app_name="Spotify")
        self.assertEqual(calls, [("open_application", {"app_name": "Spotify"})])
        self.assertEqual(results, [{"success": True, "message": "Opened Spotify"}])

        # The model's second call sees the real tool result, linked by call id
        tool_msg = provider.calls[1]["messages"][-1]
        self.assertEqual(tool_msg["role"], "tool")
        self.assertEqual(tool_msg["results"][0]["id"], "c1")
        self.assertEqual(tool_msg["results"][0]["content"], {"success": True, "message": "Opened Spotify"})
        self.assertFalse(tool_msg["results"][0]["is_error"])

        # CLAP identity, provider never named, tools passed as neutral JSON schema
        system = provider.calls[0]["system"]
        self.assertIn("You are CLAP", system)
        self.assertIn("Do not mention the underlying AI model or provider", system)
        self.assertTrue(all("parameters" in t for t in provider.calls[0]["tools"]))

        # Stored in the provider-neutral format
        stored = load_recent_history(10)
        self.assertEqual(stored[-2:], [{"role": "user", "content": "Open Spotify."},
                                       {"role": "assistant", "content": "Opening Spotify."}])

    def test_failed_tool_is_reported_as_failure(self):
        failing = mock.Mock(return_value={"success": False, "error": "Spotify could not be opened: application not found"})
        reply, _, provider = self.run_chat(
            [turn("", call("open_application", {"app_name": "Spotify"})), turn("Spotify couldn't be opened because it isn't installed.")],
            handlers={"open_application": failing},
        )
        result = provider.calls[1]["messages"][-1]["results"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("could not be opened", result["content"]["error"])
        self.assertEqual(reply, "Spotify couldn't be opened because it isn't installed.")

    def test_multiple_tool_calls_in_one_turn_and_across_rounds(self):
        executed = []

        def record(name):
            return lambda **kw: executed.append((name, kw)) or {"success": True}

        reply, history, provider = self.run_chat(
            [
                turn("", call("list_tasks", {"status": "pending"}, "a"), call("get_current_datetime", {}, "b")),
                turn("", call("add_task", {"title": "Review the CLAP HUD"}, "c")),
                turn("Task added."),
            ],
            handlers={"list_tasks": record("list_tasks"), "get_current_datetime": record("get_current_datetime"),
                      "add_task": record("add_task")},
            message="Add a task to review the CLAP HUD.",
        )
        self.assertEqual([n for n, _ in executed], ["list_tasks", "get_current_datetime", "add_task"])
        self.assertEqual(len(provider.calls), 3)
        first_results = provider.calls[1]["messages"][-1]["results"]
        self.assertEqual([r["id"] for r in first_results], ["a", "b"])   # both results in one message
        self.assertEqual(reply, "Task added.")

    def test_tool_exception_becomes_error_result(self):
        boom = mock.Mock(side_effect=RuntimeError("disk on fire"))
        _, _, provider = self.run_chat(
            [turn("", call("add_task", {"title": "x"})), turn("That failed.")],
            handlers={"add_task": boom},
        )
        result = provider.calls[1]["messages"][-1]["results"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("disk on fire", result["content"]["error"])

    def test_empty_final_text_reports_real_tool_outcome(self):
        failing = mock.Mock(return_value={"success": False, "error": "Spotify is not running"})
        reply, _, _ = self.run_chat(
            [turn("", call("close_application", {"app_name": "Spotify"})), turn("", finish="empty")],
            handlers={"close_application": failing},
        )
        self.assertEqual(reply, "That did not work: Spotify is not running")

    def test_empty_reply_without_tools_is_an_error(self):
        with self.assertRaises(agent.ClapAIError):
            self.run_chat([turn("", finish="empty")], message="hello")

    def test_malformed_and_blocked_turns(self):
        reply, _, _ = self.run_chat([turn("", finish="malformed")], message="do the thing")
        self.assertIn("rephrasing", reply)
        reply, _, _ = self.run_chat([turn("", finish="blocked")], message="something")
        self.assertEqual(reply, "I can't help with that.")

    def test_provider_errors_propagate_as_user_messages(self):
        with self.assertRaises(agent.ClapAIError) as ctx:
            self.run_chat([ai.ClapAIError("Gemini quota has been reached. Please try again later.")])
        self.assertEqual(ctx.exception.user_message, "Gemini quota has been reached. Please try again later.")

    def test_voice_mode_prompt(self):
        _, _, provider = self.run_chat([turn("Done.")], voice_mode=True)
        self.assertIn("VOICE MODE ACTIVE", provider.calls[0]["system"])

    def test_conversation_history_is_sent(self):
        history = [{"role": "user", "content": "My name is Sam."}, {"role": "assistant", "content": "Noted."}]
        _, _, provider = self.run_chat([turn("Your name is Sam.")], message="What is my name?", history=history)
        roles = [(m["role"], m["content"]) for m in provider.calls[0]["messages"]]
        self.assertEqual(roles, [("user", "My name is Sam."), ("assistant", "Noted."), ("user", "What is my name?")])

    def test_legacy_stored_history_is_normalised(self):
        # Rows written by the previous (Claude-era) version stored text blocks
        save_message("user", "hi")
        save_message("assistant", [{"type": "text", "text": "Hello. I am CLAP."}])
        legacy = load_recent_history(10)
        _, _, provider = self.run_chat([turn("Sure.")], message="again", history=legacy)
        self.assertEqual(provider.calls[0]["messages"][:2],
                         [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello. I am CLAP."}])

    def test_unknown_tool(self):
        self.assertEqual(agent.run_tool("nope", {})["success"], False)


class TrimHistoryTest(unittest.TestCase):
    def test_trim_never_starts_inside_a_tool_exchange(self):
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "", "tool_calls": [call("list_tasks")]},
            {"role": "tool", "results": [{"id": None, "name": "list_tasks", "content": {}, "is_error": False}]},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "fine"},
        ]
        trimmed = agent.trim_history(history, 4)
        self.assertEqual(trimmed[0], {"role": "user", "content": "second"})

    def test_trim_drops_leading_assistant(self):
        history = [{"role": "assistant", "content": "x"}, {"role": "user", "content": "y"}]
        self.assertEqual(agent.trim_history(history, 10), [{"role": "user", "content": "y"}])


if __name__ == "__main__":
    unittest.main()
