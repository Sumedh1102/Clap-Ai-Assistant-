"""
Gemini provider: schema and conversation adapters, response parsing, error
mapping, and the real google-genai SDK driven against a local server that
speaks the Gemini REST format (no network or API key needed).
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import httpx
from google.genai import errors, types

from tests import _env  # noqa: F401
from tests.fakes import call

import agent
import ai
import ai.gemini as gem
from database import clear_history


# ── Local Gemini REST stand-in ───────────────────────────────────────────────

class GeminiREST(BaseHTTPRequestHandler):
    """Answers POST .../models/{model}:generateContent from a scripted queue."""

    script: list = []          # items: (status, payload dict)
    requests: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        GeminiREST.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        status, payload = GeminiREST.script.pop(0)
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def candidate(*parts, finish="STOP"):
    return (200, {"candidates": [{"content": {"role": "model", "parts": list(parts)}, "finishReason": finish, "index": 0}],
                  "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
                  "modelVersion": "gemini-3.5-flash"})


def fn_call(name, args, id=None, signature=None):
    part = {"functionCall": {"name": name, "args": args, **({"id": id} if id else {})}}
    if signature:
        part["thoughtSignature"] = signature
    return part


def api_error(code, status, message, details=()):
    return (code, {"error": {"code": code, "message": message, "status": status, "details": list(details)}})


class GeminiSDKTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), GeminiREST)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        clear_history()
        GeminiREST.requests, GeminiREST.script = [], []
        fast_retry = types.HttpRetryOptions(attempts=3, initial_delay=0.01, max_delay=0.02,
                                            http_status_codes=[500, 502, 503, 504])
        self.retry_patch = mock.patch.object(gem, "RETRY", fast_retry)
        self.retry_patch.start()
        self.provider = gem.GeminiProvider(api_key="AIza-test-key", model="gemini-3.5-flash", base_url=self.base)
        ai.set_provider(self.provider)

    def tearDown(self):
        self.retry_patch.stop()
        ai.set_provider(None)

    def chat(self, message, handlers=None):
        with mock.patch.dict(agent.TOOL_HANDLERS, handlers or {}):
            return agent.chat(message, [])

    def test_tool_call_round_trip_over_the_wire(self):
        GeminiREST.script = [
            candidate(fn_call("open_application", {"app_name": "Spotify"}, id="call_1", signature="c2lnLTE=")),
            candidate({"text": "Spotify couldn't be opened because it isn't installed."}),
        ]
        failing = mock.Mock(return_value={"success": False, "error": "Application not found: Spotify"})
        reply, _ = self.chat("Open Spotify.", {"open_application": failing})

        self.assertEqual(reply, "Spotify couldn't be opened because it isn't installed.")
        failing.assert_called_once_with(app_name="Spotify")
        first, second = (r["body"] for r in GeminiREST.requests)
        self.assertIn("gemini-3.5-flash:generateContent", GeminiREST.requests[0]["path"])
        self.assertEqual(GeminiREST.requests[0]["headers"].get("x-goog-api-key"), "AIza-test-key")
        self.assertNotIn("AIza-test-key", GeminiREST.requests[0]["path"])   # key never in the URL

        # System instruction + all CLAP tools declared by their original names
        self.assertIn("You are CLAP", json.dumps(first["systemInstruction"]))
        names = [d["name"] for d in first["tools"][0]["functionDeclarations"]]
        self.assertEqual(names, [t["name"] for t in agent.TOOLS])
        decl = {d["name"]: d for d in first["tools"][0]["functionDeclarations"]}

        def schema(d):  # the SDK sends the raw JSON Schema field as parameters_json_schema
            return d.get("parameters_json_schema") or d.get("parametersJsonSchema")

        self.assertEqual(schema(decl["open_application"])["required"], ["app_name"])
        self.assertEqual(schema(decl["add_task"])["properties"]["priority"]["enum"], ["low", "medium", "high"])
        self.assertIsNone(schema(decl["get_current_datetime"]))  # no-arg tool: no schema

        # Second request replays the model turn (thought signature intact) and the real result
        model_turn, tool_turn = second["contents"][-2], second["contents"][-1]
        self.assertEqual(model_turn["role"], "model")
        self.assertEqual(model_turn["parts"][0]["thoughtSignature"], "c2lnLTE=")
        response = tool_turn["parts"][0]["functionResponse"]
        self.assertEqual((response["name"], response["id"]), ("open_application", "call_1"))
        self.assertEqual(response["response"], {"success": False, "error": "Application not found: Spotify"})

    def test_parallel_and_sequential_tool_calls(self):
        GeminiREST.script = [
            candidate(fn_call("get_current_datetime", {}, id="a"), fn_call("list_tasks", {"status": "pending"}, id="b")),
            candidate(fn_call("add_task", {"title": "Review the CLAP HUD"}, id="c")),
            candidate({"text": "Task added."}),
        ]
        added = mock.Mock(return_value={"success": True, "task_id": 7})
        reply, _ = self.chat("Add a task to review the CLAP HUD.", {
            "get_current_datetime": lambda: {"date": "Friday"},
            "list_tasks": lambda **kw: {"tasks": [], "count": 0},
            "add_task": added,
        })
        self.assertEqual(reply, "Task added.")
        added.assert_called_once_with(title="Review the CLAP HUD")
        second = GeminiREST.requests[1]["body"]["contents"][-1]["parts"]
        self.assertEqual([p["functionResponse"]["id"] for p in second], ["a", "b"])
        self.assertEqual(len(GeminiREST.requests), 3)

    def test_quota_error_is_friendly_and_not_retried(self):
        GeminiREST.script = [api_error(429, "RESOURCE_EXHAUSTED", "You exceeded your current quota.", [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
             "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"},
        ])]
        with self.assertRaises(ai.ClapAIError) as ctx:
            self.chat("hello")
        self.assertEqual(ctx.exception.user_message, "Gemini quota has been reached. Try again in 37 seconds.")
        self.assertEqual(len(GeminiREST.requests), 1)

    def test_invalid_key(self):
        GeminiREST.script = [api_error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.",
                                       [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}])]
        with self.assertRaises(ai.ClapAIError) as ctx:
            self.chat("hello")
        self.assertEqual(ctx.exception.user_message, "The Gemini API key is invalid.")

    def test_overloaded_is_retried_then_reported(self):
        GeminiREST.script = [api_error(503, "UNAVAILABLE", "The model is overloaded.")] * 3
        with self.assertRaises(ai.ClapAIError) as ctx:
            self.chat("hello")
        self.assertIn("temporarily overloaded", ctx.exception.user_message)
        self.assertEqual(len(GeminiREST.requests), 3)

    def test_overload_then_success(self):
        GeminiREST.script = [api_error(503, "UNAVAILABLE", "overloaded"), candidate({"text": "Hello. I am CLAP."})]
        reply, _ = self.chat("Who are you?")
        self.assertEqual(reply, "Hello. I am CLAP.")

    def test_malformed_function_call_is_retried_once(self):
        GeminiREST.script = [candidate(finish="MALFORMED_FUNCTION_CALL"), candidate({"text": "Opening Spotify."})]
        self.assertEqual(self.chat("Open Spotify.")[0], "Opening Spotify.")

    def test_unreachable_service(self):
        provider = gem.GeminiProvider(api_key="k", model="m", base_url="http://127.0.0.1:9")
        with self.assertRaises(ai.ClapAIError) as ctx:
            provider.generate("s", [{"role": "user", "content": "hi"}], [])
        self.assertEqual(ctx.exception.user_message, "CLAP cannot reach the AI service.")


class AdapterTest(unittest.TestCase):
    def test_missing_key(self):
        with self.assertRaises(ai.ClapAIError) as ctx:
            gem.GeminiProvider(api_key="", model="gemini-3.5-flash")
        self.assertEqual(ctx.exception.user_message, "Gemini API key is not configured.")

    def test_to_contents_roles_and_merging(self):
        contents = gem.to_contents([
            {"role": "user", "content": "one"},
            {"role": "user", "content": "two"},               # consecutive user turns are merged
            {"role": "assistant", "content": "", "tool_calls": [call("list_tasks", {"status": "all"}, "x")]},
            {"role": "tool", "results": [{"id": "x", "name": "list_tasks", "content": {"count": 0}, "is_error": False}]},
            {"role": "assistant", "content": "Nothing pending."},
        ])
        self.assertEqual([c.role for c in contents], ["user", "model", "user", "model"])
        self.assertEqual([p.text for p in contents[0].parts], ["one", "two"])
        self.assertEqual(contents[1].parts[0].function_call.name, "list_tasks")
        self.assertEqual(contents[2].parts[0].function_response.response, {"count": 0})

    def test_raw_model_content_is_replayed_exactly(self):
        raw = types.Content(role="model", parts=[types.Part(
            function_call=types.FunctionCall(name="add_task", args={"title": "x"}), thought_signature=b"sig")])
        contents = gem.to_contents([{"role": "user", "content": "go"},
                                    {"role": "assistant", "content": "", "tool_calls": [], "raw": raw}])
        self.assertIs(contents[1], raw)

    def test_parse_skips_thoughts(self):
        response = types.GenerateContentResponse(candidates=[types.Candidate(
            content=types.Content(role="model", parts=[types.Part(text="thinking...", thought=True),
                                                       types.Part(text="Opening Spotify.")]),
            finish_reason=types.FinishReason.STOP)])
        t = gem.parse_response(response)
        self.assertEqual((t.text, t.finish, t.tool_calls), ("Opening Spotify.", "stop", []))

    def test_error_mapping(self):
        def err(code, status, message, details=()):
            return errors.ClientError(code, {"error": {"code": code, "status": status, "message": message, "details": list(details)}})

        cases = [
            (err(429, "RESOURCE_EXHAUSTED", "Quota exceeded for metric: generate_content_free_tier_requests, limit: 0, model: gemini-x"),
             "has no free-tier quota"),
            (err(429, "RESOURCE_EXHAUSTED", "quota", [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]),
             "daily quota has been reached"),
            (err(404, "NOT_FOUND", "models/gemini-x is not found"), "is not available. Check GEMINI_MODEL."),
            (err(400, "FAILED_PRECONDITION", "User location is not supported for the API use."), "not available in your region"),
            (err(403, "PERMISSION_DENIED", "Permission denied"), "not permitted"),
            (errors.ServerError(500, {"error": {"code": 500, "status": "INTERNAL", "message": "internal"}}), "temporarily unavailable"),
            (httpx.ReadTimeout("timed out"), "took too long"),
            (httpx.ConnectError("refused"), "cannot reach the AI service"),
        ]
        for exc, expected in cases:
            with self.subTest(exc=repr(exc)[:60]):
                message = gem.to_clap_error(exc, "gemini-x").user_message
                self.assertIn(expected, message)
                self.assertNotIn("Traceback", message)


if __name__ == "__main__":
    unittest.main()
