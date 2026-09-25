"""Isolated test environment: temp database, dummy key, no real .env side effects."""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TMP = tempfile.mkdtemp(prefix="clap-tests-")
os.environ["DB_PATH"] = os.path.join(TMP, "test.db")
os.environ["ANTHROPIC_API_KEY"] = "test-key"
for var in ("CLAP_TTS_PROVIDER", "CLAP_TTS_API_KEY", "CLAP_TTS_VOICE_ID", "CLAP_TTS_MODEL_ID", "USER_NAME", "CLAP_MODEL"):
    os.environ[var] = ""

from database import init_db  # noqa: E402

init_db()

import logging  # noqa: E402

logging.getLogger().addHandler(logging.NullHandler())  # keep expected error logs out of test output
