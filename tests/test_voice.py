"""Voice layer: ElevenLabs HTTP contract (mock server), caching, chunking, provider selection."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from tests import _env  # noqa: F401
from tests.fakes import FakeProvider, RecordingPlayer

from voice.providers.base import TTSError
from voice.providers.elevenlabs import ElevenLabsProvider
from voice.service import VoiceService
from voice.text import split_for_speech, strip_markdown


class MockElevenLabs(BaseHTTPRequestHandler):
    requests: list = []
    status = 200

    def log_message(self, *a):
        pass

    def _record(self, body=None):
        MockElevenLabs.requests.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self._record(body)
        if self.path.startswith("/v1/voices/add/"):
            return self._json(200, {"voice_id": "added-voice-id"})
        if MockElevenLabs.status != 200:
            return self._json(MockElevenLabs.status, {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}})
        audio = b"ID3-fake-mp3:" + body["text"].encode()
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        self.end_headers()
        self.wfile.write(audio)

    def do_GET(self):
        self._record()
        self._json(200, {"voices": [{"name": "Serafina", "voice_id": "v123", "public_owner_id": "owner9",
                                     "gender": "female", "accent": "american"}]})

    def _json(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ElevenLabsProviderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), MockElevenLabs)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        MockElevenLabs.requests = []
        MockElevenLabs.status = 200
        self.provider = ElevenLabsProvider("el-key", "voice-abc", base_url=self.base)
        self.out = Path(_env.TMP) / "out.mp3"

    def test_synthesize_request_contract(self):
        self.provider.synthesize("Opening Spotify.", str(self.out))
        req = MockElevenLabs.requests[0]
        self.assertEqual(req["path"], "/v1/text-to-speech/voice-abc")
        self.assertEqual(req["headers"]["xi-api-key"], "el-key")
        self.assertEqual(req["headers"]["Accept"], "audio/mpeg")
        self.assertEqual(req["body"], {"text": "Opening Spotify.", "model_id": "eleven_multilingual_v2"})
        self.assertEqual(self.out.read_bytes(), b"ID3-fake-mp3:Opening Spotify.")

    def test_rejected_key_maps_to_user_message(self):
        MockElevenLabs.status = 401
        with self.assertRaises(TTSError) as ctx:
            self.provider.synthesize("hi", str(self.out))
        self.assertIn("Voice output is currently unavailable", ctx.exception.user_message)
        self.assertIn("Invalid API key", ctx.exception.detail)

    def test_unreachable_service(self):
        provider = ElevenLabsProvider("k", "v", base_url="http://127.0.0.1:9", timeout=2)
        with self.assertRaises(TTSError) as ctx:
            provider.synthesize("hi", str(self.out))
        self.assertEqual(ctx.exception.user_message, "Voice output is currently unavailable.")

    def test_library_search_and_add(self):
        voices = self.provider.search_library("serafina")
        self.assertEqual(voices[0]["voice_id"], "v123")
        self.assertIn("search=serafina", MockElevenLabs.requests[0]["path"])
        new_id = self.provider.add_library_voice("owner9", "v123", "CLAP")
        self.assertEqual(new_id, "added-voice-id")
        self.assertEqual(MockElevenLabs.requests[1]["path"], "/v1/voices/add/owner9/v123")
        self.assertEqual(MockElevenLabs.requests[1]["body"], {"new_name": "CLAP"})


class VoiceServiceTest(unittest.TestCase):
    def make(self, provider=None, seconds=0.01):
        self.player = RecordingPlayer(seconds)
        return VoiceService(provider or FakeProvider(), player=self.player, cache_dir=Path(_env.TMP) / "cache")

    def test_short_phrases_are_cached(self):
        provider = FakeProvider()
        service = self.make(provider)
        self.assertTrue(service.speak("Yes?", announce=False))
        self.assertTrue(service.speak("Yes?", announce=False))
        self.assertEqual(provider.calls, ["Yes?"])          # synthesised once
        self.assertEqual(len(self.player.played), 2)          # played twice

    def test_long_reply_is_chunked_in_order(self):
        provider = FakeProvider()
        service = self.make(provider)
        sentences = [f"Sentence number {i} is here to make this reply long enough." for i in range(30)]
        service.speak(" ".join(sentences), announce=False)
        self.assertGreater(len(provider.calls), 1)
        self.assertEqual(b" ".join(self.player.played).decode(), " ".join(sentences))

    def test_markdown_is_stripped(self):
        provider = FakeProvider()
        self.make(provider).speak("**Done.** See [docs](https://x.y).", announce=False)
        self.assertEqual(provider.calls, ["Done. See docs."])

    def test_is_speaking_covers_playback(self):
        service = self.make(seconds=0.1)
        self.player.probe = service.is_speaking
        service.speak("Checking the mic guard now please.", announce=False)
        self.assertEqual(self.player.observed_speaking, [True])

    def test_unavailable_service_does_not_fall_back(self):
        service = VoiceService(None, player=RecordingPlayer(), unavailable_reason="Voice output is not configured.")
        self.assertFalse(service.speak("Hello"))
        self.assertEqual(service.status()["provider"], None)
        self.assertEqual(service.last_error, "Voice output is not configured.")


class ProviderSelectionTest(unittest.TestCase):
    def build(self, **env):
        from config import config
        with mock.patch.multiple(config, **{"TTS_PROVIDER": "", "TTS_API_KEY": "", "TTS_VOICE_ID": "", "TTS_MODEL_ID": "", **env}):
            return VoiceService.from_config()

    def test_unconfigured_is_unavailable_not_fallback(self):
        service = self.build()
        self.assertIsNone(service.provider)
        self.assertIn("CLAP_TTS_API_KEY", service.status()["reason"])

    def test_elevenlabs_when_configured(self):
        service = self.build(TTS_API_KEY="k", TTS_VOICE_ID="v", TTS_MODEL_ID="eleven_flash_v2_5")
        self.assertEqual(service.provider.name, "elevenlabs")
        self.assertEqual(service.provider.model_id, "eleven_flash_v2_5")
        self.assertTrue(service.status()["reference_voice"])

    def test_explicit_none(self):
        self.assertIn("disabled", self.build(TTS_PROVIDER="none").status()["reason"])

    def test_macos_requires_macos(self):
        with mock.patch("voice.providers.macos.platform.system", return_value="Linux"):
            service = self.build(TTS_PROVIDER="macos")
        self.assertIsNone(service.provider)
        self.assertIn("macOS", service.status()["reason"])

    def test_unknown_provider(self):
        self.assertIn("Unknown", self.build(TTS_PROVIDER="espeak").status()["reason"])


class TextTest(unittest.TestCase):
    def test_split_respects_limit(self):
        chunks = split_for_speech("A. " * 400, max_chars=100)
        self.assertTrue(all(len(c) <= 100 for c in chunks))

    def test_strip(self):
        self.assertEqual(strip_markdown("# Title\n\n- one\n- two"), "Title. one two")


if __name__ == "__main__":
    unittest.main()
