"""Existing memory is preserved: installs with a jarvis.db keep using it."""

import os
import tempfile
import unittest

from tests import _env  # noqa: F401

import config


class DefaultDatabaseTest(unittest.TestCase):
    def in_dir(self, files):
        d = tempfile.mkdtemp()
        for f in files:
            open(os.path.join(d, f), "w").close()
        cwd = os.getcwd()
        os.chdir(d)
        try:
            return config._default_db_path()
        finally:
            os.chdir(cwd)

    def test_new_install_uses_clap_db(self):
        self.assertEqual(self.in_dir([]), "clap.db")

    def test_existing_jarvis_db_is_kept(self):
        self.assertEqual(self.in_dir(["jarvis.db"]), "jarvis.db")

    def test_clap_db_wins_when_both_exist(self):
        self.assertEqual(self.in_dir(["jarvis.db", "clap.db"]), "clap.db")


if __name__ == "__main__":
    unittest.main()
