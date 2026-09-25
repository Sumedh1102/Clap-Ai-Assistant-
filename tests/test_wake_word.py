"""Wake word "CLAP": sensible Whisper variants match; sounds and other words do not."""

import unittest

from tests import _env  # noqa: F401

from tools.voice_input import wake_word_in


class WakeWordTest(unittest.TestCase):
    def test_matches(self):
        for text in ["Clap.", "CLAP", "clap", "Hey, CLAP.", "hey clap", "Hey clap, open Spotify.",
                     "C.L.A.P.", "c-l-a-p", "Klap!", "Clapp."]:
            with self.subTest(text=text):
                self.assertTrue(wake_word_in(text))

    def test_rejects(self):
        for text in ["(clapping)", "[APPLAUSE]", "*claps*", "They were clapping loudly", "claps",
                     "clapped", "clapboard", "Thank you.", "", "Jarvis"]:
            with self.subTest(text=text):
                self.assertFalse(wake_word_in(text))


if __name__ == "__main__":
    unittest.main()
