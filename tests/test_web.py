"""Flask HUD server: routing, local-only guard, chat via session, live SSE stream."""

import json
import threading
import time
import unittest
import urllib.request
from unittest import mock

from tests import _env  # noqa: F401

import web.app as webapp
from events import AssistantState, hub
from session import TurnResult


class WebTest(unittest.TestCase):
    def setUp(self):
        self.client = webapp.app.test_client()

    def test_local_only(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/api/health", headers={"Host": "127.0.0.1:7777"}).status_code, 200)
        self.assertEqual(self.client.get("/api/health", headers={"Host": "attacker.test"}).status_code, 403)

    def test_chat_goes_through_session(self):
        fake = mock.Mock()
        fake.handle.return_value = TurnResult(ok=True, reply="Opening Spotify.", message_id=7)
        with mock.patch.object(webapp, "get_session", return_value=fake):
            r = self.client.post("/api/chat", json={"message": "Open Spotify."})
        self.assertEqual(r.get_json()["reply"], "Opening Spotify.")
        fake.handle.assert_called_once_with("Open Spotify.", source="web", wait=True)

    def test_chat_error_is_friendly(self):
        fake = mock.Mock()
        fake.handle.return_value = TurnResult(ok=False, error="CLAP cannot reach the AI service.")
        with mock.patch.object(webapp, "get_session", return_value=fake):
            r = self.client.post("/api/chat", json={"message": "hi"})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json(), {"error": "CLAP cannot reach the AI service.", "message_id": None})

    def test_chat_requires_message(self):
        self.assertEqual(self.client.post("/api/chat", json={}).status_code, 400)

    def test_state_and_system(self):
        state = self.client.get("/api/state").get_json()
        self.assertEqual(state["assistant"], "CLAP")
        self.assertIn(state["state"], [s.value for s in AssistantState])
        system = self.client.get("/api/system").get_json()
        for key in ("cpu_percent", "memory_percent", "mic", "voice", "model"):
            self.assertIn(key, system)

    def test_console_is_clap_branded(self):
        html = self.client.get("/console").get_data(as_text=True)
        self.assertIn("CLAP", html)
        self.assertNotIn("J.A.R.V.I.S", html)
        self.assertNotIn("JARVIS", html)


class EventStreamTest(unittest.TestCase):
    """Real HTTP server + SSE client: events reach subscribers live."""

    def test_sse_snapshot_then_live_events(self):
        server = webapp.run_web(port=0, open_browser=False)
        port = server.server_port
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events", timeout=5)
            self.assertEqual(resp.headers.get_content_type(), "text/event-stream")
            events = []

            def read():
                for raw in resp:
                    line = raw.decode().strip()
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))
                        if len(events) >= 3:
                            return

            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            deadline = time.time() + 5
            while not events and time.time() < deadline:
                time.sleep(0.05)
            hub.set_state(AssistantState.LISTENING, "Listening")
            hub.add_message("user", "Open Spotify.", "voice")
            reader.join(5)
            resp.close()
        finally:
            server.shutdown()

        self.assertEqual(events[0]["type"], "snapshot")
        self.assertEqual(events[0]["assistant"], "CLAP")
        self.assertEqual((events[1]["type"], events[1]["state"]), ("state", "listening"))
        self.assertEqual((events[2]["type"], events[2]["text"]), ("message", "Open Spotify."))


class PortInUseTest(unittest.TestCase):
    def test_busy_port_raises_instead_of_exiting(self):
        import socket
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        try:
            with self.assertRaises(OSError):
                webapp.run_web(port=sock.getsockname()[1], open_browser=False)
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
