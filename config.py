"""Central configuration — loads .env and exposes typed settings."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_DIR = Path(__file__).resolve().parent


def _default_db_path() -> str:
    """
    CLAP stores its memory in clap.db. Installs that predate the rename keep
    using their existing jarvis.db so no tasks, notes or history are lost.
    """
    if Path("clap.db").exists():
        return "clap.db"
    if Path("jarvis.db").exists():
        return "jarvis.db"
    return "clap.db"


class Config:
    ASSISTANT_NAME: str = "CLAP"

    ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
    BRAVE_API_KEY: str = os.environ.get("BRAVE_API_KEY", "")
    GMAIL_ADDRESS: str = os.environ.get("GMAIL_ADDRESS", "")
    GMAIL_APP_PASSWORD: str = os.environ.get("GMAIL_APP_PASSWORD", "")
    DEFAULT_EMAIL: str = os.environ.get("DEFAULT_EMAIL", "")
    DB_PATH: str = os.environ.get("DB_PATH") or _default_db_path()
    MODEL: str = os.environ.get("CLAP_MODEL", "claude-opus-4-6")
    MAX_TOKENS: int = 4096
    HISTORY_LIMIT: int = 40
    PICOVOICE_ACCESS_KEY: str = os.environ.get("PICOVOICE_ACCESS_KEY", "")
    MORNING_BRIEFING_TIME: str = os.environ.get("MORNING_BRIEFING_TIME", "08:00")
    USER_NAME: str = os.environ.get("USER_NAME", "").strip()
    WEB_PORT: int = int(os.environ.get("WEB_PORT", "7777"))

    # ── Voice output (see voice/ and README → Voice) ──────────────────────────
    # Provider: "elevenlabs" (CLAP reference voice), "macos" (explicit opt-in
    # approximation), or "none". Empty = elevenlabs when its key + voice are set.
    TTS_PROVIDER: str = os.environ.get("CLAP_TTS_PROVIDER", "").strip().lower()
    TTS_API_KEY: str = os.environ.get("CLAP_TTS_API_KEY", "")
    TTS_VOICE_ID: str = os.environ.get("CLAP_TTS_VOICE_ID", "").strip()
    TTS_MODEL_ID: str = os.environ.get("CLAP_TTS_MODEL_ID", "").strip()

    LOG_DIR: Path = PROJECT_DIR / "logs"

    def validate(self) -> list[str]:
        """Return list of missing required keys."""
        missing = []
        if not self.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")
        return missing


config = Config()
