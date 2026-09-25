#!/usr/bin/env python3
"""
CLAP — personal AI assistant. Entry point.

Modes:
  python clap.py                → interactive CLI
  python clap.py --voice        → voice mode: say "CLAP" (HUD served at localhost:7777)
  python clap.py --web          → CLAP HUD at localhost:7777 (opens the browser)
  python clap.py --voice --web  → voice mode and open the HUD
  python clap.py --briefing     → print daily briefing and exit
  python clap.py --clear        → wipe conversation history and exit
  python clap.py "message"      → single-shot message

Options: --mute (no spoken replies), --no-overlay, --no-browser, --no-hud
"""

import argparse
import logging
import logging.handlers
import queue
import signal
import sys
import threading

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.theme import Theme

from config import config
from database import clear_history, init_db, load_recent_history
from events import AssistantState, hub

# ── Theme & console ───────────────────────────────────────────────────────────

THEME = Theme({
    "clap":  "bold #b9a8ff",
    "user":  "bold #e6e1ff",
    "tool":  "dim #ffcf99",
    "error": "bold #ff5c6c",
    "info":  "dim",
    "voice": "bold #d7a8ff",
})
console = Console(theme=THEME)

BANNER = """
  ██████╗ ██╗      █████╗ ██████╗
 ██╔════╝ ██║     ██╔══██╗██╔══██╗
 ██║      ██║     ███████║██████╔╝
 ██║      ██║     ██╔══██║██╔═══╝
 ╚██████╗ ███████╗██║  ██║██║
  ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝
"""

HELP_TEXT = """\
**Commands**
- `/briefing`  — daily morning briefing
- `/tasks`     — list pending tasks
- `/clear`     — wipe conversation history
- `/help`      — show this message
- `/quit`      — exit

**Modes**
- `--voice`    — voice activation: say "CLAP"
- `--web`      — CLAP HUD at localhost:7777
"""

WAKE_ACK = "Yes?"
ONLINE_GREETING = "CLAP online."

log = logging.getLogger("clap")


class _RedactSecrets(logging.Filter):
    """Never let an API key or password reach a log file."""

    def __init__(self, secrets: list) -> None:
        super().__init__()
        self._secrets = [x for x in secrets if x and len(x) >= 6]

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secrets:
            message = record.getMessage()
            if any(x in message for x in self._secrets):
                for x in self._secrets:
                    message = message.replace(x, "[redacted]")
                record.msg, record.args = message, ()
        return True


def _setup_logging() -> None:
    """Technical details go to logs/clap.log; the console shows user-facing text only."""
    config.LOG_DIR.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        config.LOG_DIR / "clap.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(_RedactSecrets([
        config.GEMINI_API_KEY, config.TTS_API_KEY, config.BRAVE_API_KEY, config.GMAIL_APP_PASSWORD,
    ]))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)


# ── Shared helpers ────────────────────────────────────────────────────────────

def on_tool_call(name: str, inputs: dict) -> None:
    from tools.labels import describe_tool_call
    label, action = describe_tool_call(name, inputs)
    console.print(f"  [tool]⚙  {label} · {action}[/tool]")


def print_clap(text: str) -> None:
    if not text.strip():
        return
    console.print()
    console.print(Panel(Markdown(text), title="[clap]CLAP[/clap]", border_style="#6e62a0"))


def _voice_status_panel(speaking_enabled: bool) -> None:
    import voice
    st = voice.status()
    if st["available"] and speaking_enabled:
        note = "" if st["reference_voice"] else "\n[info]Note: this is an approximation, not the CLAP reference voice.[/info]"
        console.print(f"[info]Voice output:[/info] {st['voice']}{note}")
    elif st["available"]:
        console.print("[info]Voice output muted (--mute).[/info]")
    else:
        console.print(Panel(
            f"[error]Voice output is currently unavailable.[/error]\n[info]{st['reason']}[/info]\n"
            "[info]Replies are shown in the HUD and terminal. See README → Voice to configure CLAP's voice.[/info]",
            border_style="#ff5c6c",
        ))


def _start_scheduler(session=None) -> "queue.Queue[str]":
    """Scheduled events run through the session when there is one, else queue for the CLI."""
    from tools.scheduler import start_scheduler
    events: "queue.Queue[str]" = queue.Queue()

    def _on_event(msg: str) -> None:
        if session is None:
            events.put(msg)
            return
        threading.Thread(
            target=session.handle, args=(msg,), kwargs={"source": "scheduler"}, daemon=True
        ).start()

    start_scheduler(_on_event)
    return events


def _start_hud(session, open_browser: bool) -> bool:
    from web.app import run_web
    try:
        run_web(port=config.WEB_PORT, open_browser=open_browser, session=session)
    except OSError as exc:
        console.print(f"[error]CLAP HUD could not start on port {config.WEB_PORT}: {exc.strerror or exc}[/error]")
        log.error("HUD failed to start: %s", exc)
        return False
    console.print(f"[clap]CLAP HUD[/clap] [info]→[/info] [bold]http://127.0.0.1:{config.WEB_PORT}[/bold]")
    return True


# ── CLI session ───────────────────────────────────────────────────────────────

def run_cli(initial_message: str = "") -> None:
    from agent import ClapAIError, chat

    scheduled = _start_scheduler()
    history = load_recent_history(config.HISTORY_LIMIT)

    def send(message: str) -> None:
        nonlocal history
        try:
            reply, history = chat(message, history, on_tool_call=on_tool_call)
            print_clap(reply)
        except ClapAIError as exc:
            console.print(f"[error]{exc.user_message}[/error]")
        except Exception:
            log.exception("CLI command failed")
            console.print("[error]CLAP hit an internal error. Details are in logs/clap.log.[/error]")

    if initial_message:
        send(initial_message)
        return

    console.print(f"[clap]{BANNER}[/clap]")
    console.print(Panel("[info]CLAP online. Type a command, or /help.[/info]", border_style="dim"))
    prompt_label = config.USER_NAME.capitalize() if config.USER_NAME else "You"

    while True:
        while not scheduled.empty():
            msg = scheduled.get_nowait()
            console.print(f"\n[clap]⏰ Scheduled:[/clap] {msg}")
            send(msg)

        try:
            user_input = Prompt.ask(f"\n[user]{prompt_label}[/user]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[info]CLAP offline.[/info]")
            break

        if not user_input:
            continue
        lowered = user_input.lower()
        if lowered in ("/quit", "/exit", "/q"):
            console.print("[info]CLAP offline.[/info]")
            break
        if lowered == "/help":
            console.print(Markdown(HELP_TEXT))
            continue
        if lowered == "/clear":
            clear_history()
            history = []
            console.print("[info]Conversation history cleared.[/info]")
            continue
        if lowered == "/briefing":
            user_input = "Give me my daily briefing."
        if lowered == "/tasks":
            user_input = "List all my pending tasks."

        try:
            send(user_input)
        except KeyboardInterrupt:
            console.print("\n[info](interrupted)[/info]")


# ── Voice mode ────────────────────────────────────────────────────────────────

def run_voice(args) -> None:
    """
    Voice mode: persistent microphone stream, wake word "CLAP", Whisper STT,
    AI (Gemini) + tools, spoken reply. The HUD (web) and the floating overlay both
    mirror the real state from the event hub.
    """
    import voice
    from session import ClapSession
    from tools.voice_input import run_voice_loop, wake_word_available

    service = voice.get_service()
    speaking = service.available and not args.mute
    session = ClapSession(speak_replies=speaking, voice_mode=True)
    hub.set_mode("voice")
    _start_scheduler(session)

    console.print(f"[clap]{BANNER}[/clap]")
    _voice_status_panel(speaking)
    if not args.no_hud:
        _start_hud(session, open_browser=args.web and not args.no_browser)
    if speaking:
        service.warm([WAKE_ACK, ONLINE_GREETING])

    overlay = None
    if not args.no_overlay:
        try:
            from tools.overlay import ClapOverlay
            overlay = ClapOverlay()
            hub.add_listener(overlay.on_event)
        except Exception as exc:  # tkinter missing (e.g. some Homebrew Pythons)
            console.print(f"[info]Floating overlay unavailable ({exc}); continuing without it.[/info]")
            overlay = None

    stop_event = threading.Event()

    def speak(text: str, **kwargs) -> None:
        if speaking:
            voice.speak(text, **kwargs)

    def on_wake() -> None:
        if session.busy:
            return
        hub.set_mic("capturing")
        hub.set_state(AssistantState.LISTENING)
        speak(WAKE_ACK, then_state=AssistantState.LISTENING)

    def on_capture_start() -> None:
        if not session.busy:
            hub.set_mic("capturing")
            hub.set_state(AssistantState.LISTENING)

    def on_transcribing() -> None:
        hub.set_mic("armed")
        if not session.busy:
            hub.set_state(AssistantState.THINKING, "Transcribing")

    def on_no_speech() -> None:
        if not session.busy:
            hub.set_state(AssistantState.STANDBY)

    def on_ready() -> None:
        hub.set_mic("armed")
        hub.set_state(AssistantState.STANDBY)

    def on_command(text: str) -> None:
        console.print(f"[user]You:[/user] {text}")
        result = session.handle(text, source="voice", wait=False)
        if result.ok:
            print_clap(result.reply)
        else:
            console.print(f"[error]{result.error}[/error]")

    def _voice_thread() -> None:
        try:
            if wake_word_available():
                console.print(Panel(
                    '[voice]Voice mode active.[/voice] Say "[bold]CLAP[/bold]" to activate.\n'
                    "[info]Ctrl+C to exit.[/info]",
                    border_style="#6e62a0",
                ))
                speak(ONLINE_GREETING)
                run_voice_loop(
                    on_command=on_command,
                    on_wake=on_wake,
                    stop_event=stop_event,
                    on_capture_start=on_capture_start,
                    on_transcribing=on_transcribing,
                    on_no_speech=on_no_speech,
                    is_output_active=service.is_speaking,
                    on_ready=on_ready,
                )
            else:
                _push_to_talk(stop_event, on_command, speak)
        except Exception as exc:
            log.exception("voice loop failed")
            hub.set_mic("unavailable")
            hub.set_error("Microphone input is unavailable.")
            console.print(f"[error]Microphone input is unavailable: {exc}[/error]")
            stop_event.wait()
        finally:
            if overlay:
                overlay.stop()

    def _shutdown(*_):
        stop_event.set()
        voice.stop()
        if overlay:
            overlay.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    threading.Thread(target=_voice_thread, name="clap-voice", daemon=True).start()

    if overlay:
        overlay.run()          # blocks on the main thread until stopped
    else:
        while not stop_event.wait(0.5):
            pass
    stop_event.set()
    console.print("[info]CLAP offline.[/info]")


def _push_to_talk(stop_event: threading.Event, on_command, speak) -> None:
    """Fallback when the wake word engine is unavailable: press Enter to talk."""
    from tools.voice_input import record_until_silence, transcribe

    console.print(Panel(
        "[voice]Voice mode — press-to-talk.[/voice]\n"
        "Press [bold]Enter[/bold] to speak · [bold]Ctrl+C[/bold] to exit.",
        border_style="#6e62a0",
    ))
    hub.set_mic("off")
    speak("CLAP online. Press Enter to speak.")
    while not stop_event.is_set():
        try:
            console.print("\n[info]Press Enter to speak...[/info]")
            input()
        except (KeyboardInterrupt, EOFError):
            stop_event.set()
            break
        hub.set_mic("capturing")
        hub.set_state(AssistantState.LISTENING)
        audio = record_until_silence()
        hub.set_mic("off")
        hub.set_state(AssistantState.THINKING, "Transcribing")
        text = transcribe(audio)
        if text:
            threading.Thread(target=on_command, args=(text,), daemon=True).start()
        else:
            console.print("[info](silence detected)[/info]")
            hub.set_state(AssistantState.STANDBY)


# ── Web mode ──────────────────────────────────────────────────────────────────

def run_web(args) -> None:
    import voice
    from session import ClapSession

    service = voice.get_service()
    speaking = service.available and not args.mute
    # When CLAP speaks its replies, ask for short, speakable answers.
    session = ClapSession(speak_replies=speaking, voice_mode=speaking)
    hub.set_mode("web")
    _start_scheduler(session)

    console.print(f"[clap]{BANNER}[/clap]")
    _voice_status_panel(speaking)
    if not _start_hud(session, open_browser=not args.no_browser):
        sys.exit(1)
    console.print("[info]Press Ctrl+C to stop.[/info]")

    stop_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    try:
        while not stop_event.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    voice.stop()
    console.print("\n[info]CLAP offline.[/info]")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="CLAP — personal AI assistant")
    parser.add_argument("--voice",      action="store_true", help='Voice mode (say "CLAP")')
    parser.add_argument("--web",        action="store_true", help="CLAP HUD web interface")
    parser.add_argument("--briefing",   action="store_true", help="Print daily briefing and exit")
    parser.add_argument("--clear",      action="store_true", help="Clear conversation history and exit")
    parser.add_argument("--mute",       action="store_true", help="Do not speak replies")
    parser.add_argument("--no-overlay", action="store_true", help="Voice mode without the floating overlay")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the HUD in a browser")
    parser.add_argument("--no-hud",     action="store_true", help="Voice mode without the web HUD server")
    parser.add_argument("message",      nargs="?",           help="Single message (non-interactive)")
    args = parser.parse_args()

    _setup_logging()

    missing = config.validate()
    if missing:
        console.print(
            f"[error]Missing required environment variables: {', '.join(missing)}\n"
            "Copy .env.example → .env and fill in the values.[/error]"
        )
        sys.exit(1)

    init_db()

    if args.clear:
        clear_history()
        console.print("[info]Conversation history cleared.[/info]")
        return

    if args.briefing:
        run_cli("Give me my daily briefing.")
        return

    if args.voice:
        run_voice(args)
        return

    if args.web:
        run_web(args)
        return

    if args.message:
        run_cli(args.message)
        return

    run_cli()


if __name__ == "__main__":
    main()
