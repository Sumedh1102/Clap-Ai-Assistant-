"""
CLAP voice utility.

  python -m voice status                 show the configured voice
  python -m voice test ["text"]          speak a test phrase
  python -m voice find serafina          search the ElevenLabs Voice Library
  python -m voice add OWNER_ID VOICE_ID  add a library voice to your account
"""

from __future__ import annotations

import argparse
import sys

from config import config


def _elevenlabs():
    from voice.providers.elevenlabs import ElevenLabsProvider
    if not config.TTS_API_KEY:
        sys.exit("Set CLAP_TTS_API_KEY (your ElevenLabs API key) in .env first.")
    # The voice ID is not needed for library calls; a placeholder satisfies the constructor.
    return ElevenLabsProvider(config.TTS_API_KEY, config.TTS_VOICE_ID or "-")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m voice", description="CLAP voice utility")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status", help="Show the configured voice")
    p_test = sub.add_parser("test", help="Speak a test phrase")
    p_test.add_argument("text", nargs="?", default="Hello. I am CLAP.")
    p_find = sub.add_parser("find", help="Search the ElevenLabs Voice Library")
    p_find.add_argument("query")
    p_add = sub.add_parser("add", help="Add a Voice Library voice to your ElevenLabs account")
    p_add.add_argument("public_owner_id")
    p_add.add_argument("voice_id")
    p_add.add_argument("--name", default="CLAP")
    args = parser.parse_args()

    if args.cmd == "find":
        voices = _elevenlabs().search_library(args.query)
        if not voices:
            print("No voices found.")
        for v in voices:
            print(f"{v.get('name')}")
            print(f"  voice_id        {v.get('voice_id')}")
            print(f"  public_owner_id {v.get('public_owner_id')}")
            details = ", ".join(str(v[k]) for k in ("gender", "age", "accent", "descriptive", "use_case") if v.get(k))
            if details:
                print(f"  {details}")
            if v.get("preview_url"):
                print(f"  preview         {v['preview_url']}")
        if voices:
            print("\nAdd one with:  python -m voice add <public_owner_id> <voice_id>")
        return

    if args.cmd == "add":
        new_id = _elevenlabs().add_library_voice(args.public_owner_id, args.voice_id, args.name)
        print(f"Added. Put this in .env:\n  CLAP_TTS_VOICE_ID={new_id}")
        return

    from voice import get_service
    service = get_service()
    status = service.status()
    if args.cmd == "test":
        if not service.available:
            sys.exit(status["reason"])
        ok = service.speak(args.text, announce=False)
        print("Spoken." if ok else f"Failed: {service.last_error}")
        sys.exit(0 if ok else 1)

    print(f"Voice available : {status['available']}")
    print(f"Provider        : {status['provider'] or '-'}")
    print(f"Voice           : {status['voice'] or '-'}")
    print(f"Reference voice : {status['reference_voice']}")
    if status["reason"]:
        print(f"Note            : {status['reason']}")


if __name__ == "__main__":
    main()
