"""
Voice input state machine with a simulated microphone and a stub Whisper.

Real Whisper weights and audio hardware are not available in CI; this checks
the wake → capture → transcribe → command flow, the HUD hooks, and that CLAP
ignores the microphone while it is speaking.
"""

import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from tests import _env  # noqa: F401

from tools import voice_input as vi

SR = vi.SR


def tone(seconds: float, amp: float = 0.2) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype("float32")


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), dtype="float32")


class FakeInputStream:
    """Feeds a prepared signal to the callback in BLOCKSIZE frames, ~20x real time."""

    signal: np.ndarray = silence(1)

    def __init__(self, samplerate, channels, dtype, blocksize, callback):
        self.callback, self.blocksize = callback, blocksize

    def __enter__(self):
        def feed():
            for i in range(0, len(self.signal) - self.blocksize, self.blocksize):
                self.callback(self.signal[i:i + self.blocksize].reshape(-1, 1), self.blocksize, None, None)
                time.sleep(self.blocksize / SR / 20)
        threading.Thread(target=feed, daemon=True).start()
        return self

    def __exit__(self, *a):
        return False


class StubWhisper:
    """Wake scans (vad_filter=False) hear 'Hey, CLAP.'; command transcription hears the command."""

    def __init__(self, command="Open Spotify."):
        self.command = command

    def transcribe(self, audio, beam_size, language, vad_filter):
        loud = float(np.sqrt(np.mean(audio ** 2))) > 0.05
        if not loud:
            return iter([]), None
        return iter([SimpleNamespace(text=self.command if vad_filter else "Hey, CLAP.")]), None


class VoiceLoopTest(unittest.TestCase):
    def run_loop(self, signal, is_output_active=None, timeout=20.0):
        FakeInputStream.signal = signal
        events, done = [], threading.Event()
        stop = threading.Event()

        def on_command(text):
            events.append(("command", text))
            done.set()

        hooks = dict(
            on_wake=lambda: events.append(("wake",)),
            on_capture_start=lambda: events.append(("capture",)),
            on_transcribing=lambda: events.append(("transcribing",)),
            on_no_speech=lambda: events.append(("no_speech",)),
            on_ready=lambda: events.append(("ready",)),
            is_output_active=is_output_active,
        )
        with mock.patch.object(vi, "_SD_OK", True), \
             mock.patch.object(vi, "sd", SimpleNamespace(InputStream=FakeInputStream), create=True), \
             mock.patch.object(vi, "_get_whisper", return_value=StubWhisper()):
            t = threading.Thread(target=vi.run_voice_loop, args=(on_command,), kwargs={"stop_event": stop, **hooks}, daemon=True)
            t.start()
            done.wait(timeout)
            stop.set()
            t.join(5)
        return events

    def test_wake_then_command(self):
        signal = np.concatenate([silence(1.0), tone(1.5), silence(0.3), tone(1.2), silence(2.5)])
        events = self.run_loop(signal)
        names = [e[0] for e in events]
        self.assertEqual(names[0], "ready")
        self.assertIn("wake", names)
        self.assertLess(names.index("wake"), names.index("capture"))
        self.assertLess(names.index("capture"), names.index("transcribing"))
        self.assertEqual(events[-1], ("command", "Open Spotify."))

    def test_no_self_wake_while_speaking(self):
        signal = np.concatenate([silence(0.5), tone(2.0), silence(2.0)])
        events = self.run_loop(signal, is_output_active=lambda: True, timeout=4.0)
        self.assertNotIn("wake", [e[0] for e in events])


if __name__ == "__main__":
    unittest.main()
