"""
CLAP AI utility.

  python -m ai check     verify GEMINI_API_KEY and GEMINI_MODEL with one small request
  python -m ai models    list the Gemini models your key can use
"""

from __future__ import annotations

import argparse
import logging
import sys

from config import config


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m ai", description="CLAP AI utility")
    parser.add_argument("cmd", choices=["check", "models"])
    args = parser.parse_args()
    logging.getLogger().addHandler(logging.NullHandler())  # user-facing output only

    from ai import ClapAIError, get_provider
    try:
        provider = get_provider()
        if args.cmd == "models":
            models = provider.list_models()
            for m in models:
                marker = "  ← GEMINI_MODEL" if m["name"] == config.MODEL else ""
                print(f"{m['name']:<40} {m['display_name']}{marker}")
            if not any(m["name"] == config.MODEL for m in models):
                print(f"\nGEMINI_MODEL={config.MODEL} is not in this list.")
            return
        turn = provider.generate("Reply with exactly: CLAP online.", [{"role": "user", "content": "Status?"}], [])
        print(f"Provider : {provider.name}")
        print(f"Model    : {config.MODEL}")
        print(f"Reply    : {turn.text or '(empty)'}")
    except ClapAIError as exc:
        sys.exit(exc.user_message)


if __name__ == "__main__":
    main()
