"""macOS app control: honest results, no AppleScript injection."""

import subprocess
import unittest
from unittest import mock

from tests import _env  # noqa: F401

from tools import apps


def completed(code=0, out="", err=""):
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=out, stderr=err)


class MacAppControlTest(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch.object(apps, "_SYSTEM", "Darwin")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_open_success(self):
        with mock.patch.object(apps.subprocess, "run", return_value=completed(0)) as run:
            self.assertEqual(apps.open_application("Spotify"), {"success": True, "message": "Opened Spotify"})
        run.assert_called_once_with(["open", "-a", "Spotify"], capture_output=True, text=True)

    def test_open_failure_is_reported(self):
        with mock.patch.object(apps.subprocess, "run", return_value=completed(1, err="Unable to find application named 'Spotfy'")):
            result = apps.open_application("Spotfy")
        self.assertFalse(result["success"])
        self.assertIn("could not be opened", result["error"])

    def test_close_passes_name_as_argument_not_script(self):
        evil = 'Finder" to do shell script "rm -rf ~'
        with mock.patch.object(apps.subprocess, "run", return_value=completed(0, out="closed")) as run:
            apps.close_application(evil)
        argv = run.call_args[0][0]
        self.assertEqual(argv[0], "osascript")
        self.assertEqual(argv[-1], evil)                       # passed as argv
        self.assertTrue(all(evil not in part for part in argv[:-1]))  # never inside the script

    def test_close_not_running_is_not_success(self):
        with mock.patch.object(apps.subprocess, "run", return_value=completed(0, out="not running\n")):
            result = apps.close_application("Spotify")
        self.assertEqual(result, {"success": False, "error": "Spotify is not running"})

    def test_close_fallback_uses_exact_match(self):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return completed(1) if argv[0] == "osascript" else completed(1)

        with mock.patch.object(apps.subprocess, "run", side_effect=run):
            result = apps.close_application("Notes")
        self.assertEqual(calls[1], ["pkill", "-x", "Notes"])
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
