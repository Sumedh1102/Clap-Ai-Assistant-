# CLAP
### Personal AI assistant

CLAP is a voice-first personal AI assistant for macOS. Say **"CLAP"**, give a command,
and it reasons with Claude, acts through real tools (apps, browser, search, tasks,
email, memory) and answers in its own voice. A cinematic HUD built around the ThreeUI
**Predictive Arc** shows what CLAP is doing at every moment.

---

## What CLAP does

| Feature | Description |
|---|---|
| 🎙 **Wake word** | Say *"CLAP"* or *"Hey CLAP"*. Detected locally with Whisper, no cloud STT. |
| 🔊 **CLAP voice** | Replies in the CLAP reference voice (ElevenLabs), with no silent fallback to another voice |
| 🌌 **CLAP HUD** | The ThreeUI `PredictiveArcCanvas` at the centre, live state, conversation, tool activity and system info at `localhost:7777` |
| 🖥 **App control** | Open and close macOS apps, reporting honestly when that fails |
| 🌐 **Browser automation** | Navigate, read, click, fill and screenshot via Playwright |
| 🔍 **Web search** | Live results via Brave Search (optional) |
| ✅ **Tasks** | Create, update, complete and delete tasks (SQLite) |
| 🧠 **Memory** | Knowledge base of notes, documents and imported Claude chats (SQLite FTS5) |
| 📧 **Email** | Send via Gmail SMTP, with attachments (optional) |
| ☀️ **Daily briefing** | Scheduled morning summary and overdue-task reminders |
| 🪟 **Overlay** | Small floating status overlay in voice mode |
| 🚀 **Autostart** | Starts on login via a macOS LaunchAgent |

---

## Architecture

```
                    CLAP
                      │
          ┌───────────┴───────────┐
          │                       │
      FRONTEND                 BACKEND
   Predictive Arc HUD      Python agent + Flask
   (React, ThreeUI)        (clap.py, session.py)
          │    ▲                  │
          │    └── live events ───┤  server-sent events (/api/events)
          └───── commands ───────►│  POST /api/chat
                                  │
                                Claude  (agent.py — tool-use loop)
                                  │
            ┌─────────────┬───────┼────────┬─────────────┐
            │             │       │        │             │
         macOS         Browser  Search   Tasks /      Email
         apps        (Playwright) (Brave) Memory     (Gmail)
                                          (SQLite)
```

### Voice pipeline

```
MICROPHONE (one persistent stream)
   ↓  wake word "CLAP"      tools/voice_input.py  (Whisper)       HUD: STANDBY → LISTENING
   ↓  record until silence
   ↓  Whisper STT                                                 HUD: THINKING (Transcribing)
   ↓  session.handle()      session.py                            HUD: THINKING
   ↓  Claude + tools        agent.py                              HUD: EXECUTING ⇄ THINKING
   ↓  reply text
   ↓  voice.speak()         voice/ (ElevenLabs → afplay)          HUD: SPEAKING (only while audio plays)
   ↓                                                              HUD: STANDBY
   any failure                                                    HUD: ERROR + short message
```

Every HUD state comes from a real event in `events.py`, the single source of truth that
the web HUD and the floating overlay both subscribe to. No state is simulated with timers.

### Project structure

```
clap.py                 Entry point: CLI / --voice / --web
jarvis.py               Compatibility shim (runs clap.py)
agent.py                Claude tool-use loop, CLAP system prompt, error mapping
session.py              Shared pipeline for voice, HUD and scheduler → real state events
events.py               Event hub: state, conversation, tool activity, mic, voice
config.py               .env loader + typed settings
database.py             SQLite: tasks, conversation history, knowledge base
autostart.py            macOS LaunchAgent installer
debug_voice.py          Microphone / wake-word diagnostic

voice/                  Voice output: speak(text)
  service.py            provider selection, chunking, caching, SPEAKING state, mic guard
  playback.py           afplay (macOS) / ffplay / mpg123 / mpv
  providers/            elevenlabs.py (CLAP voice) · macos.py (explicit opt-in)
  __main__.py           python -m voice status | test | find | add

tools/                  Agent tools (tasks, email, search, browser, apps, KB, briefing,
                        scheduler), voice_input.py (wake word + STT), overlay.py, labels.py

web/
  app.py                Flask: HUD, /api/events (SSE), /api/state, /api/system, /api/chat, KB, tasks
  system.py             Real CPU / memory metrics (psutil)
  templates/console.html  Text console: knowledge base import + task manifest (/console)
  frontend/             CLAP HUD (React + TypeScript + Vite)
    src/components/ClapCore/  ClapCore.tsx — PredictiveArcCanvas + state display

tests/                  unittest suite (no network needed)
docs/                   THREEUI_VERIFICATION.md · VOICE.md
```

---

## Prerequisites (macOS, Apple Silicon)

```bash
uname -m            # arm64
python3 --version   # 3.10+ recommended (Homebrew: brew install python@3.12)
node --version      # 20.19+ (Homebrew: brew install node)
```

Apple's built-in `/usr/bin/python3` (3.9) also works, but pip then installs an older
Anthropic SDK. The floating overlay needs Tk: with Homebrew Python, run
`brew install python-tk@3.12`, or use `--no-overlay`.

## Setup

### 1. Python backend

```bash
git clone https://github.com/Sumedh1102/Clap-Ai-Assistant-.git
cd Clap-Ai-Assistant-
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
playwright install chromium
```

### 2. Frontend (CLAP HUD)

```bash
npm install
npm run build        # builds web/frontend/dist, served by the backend at :7777
```

### 3. Configure

```bash
cp .env.example .env
```

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Claude. Get a key at [console.anthropic.com](https://console.anthropic.com) |
| `CLAP_TTS_API_KEY` | for voice | ElevenLabs API key |
| `CLAP_TTS_VOICE_ID` | for voice | ID of the CLAP voice in your ElevenLabs account (see below) |
| `CLAP_TTS_MODEL_ID` | optional | `eleven_multilingual_v2` (default) or `eleven_flash_v2_5` (lower latency) |
| `CLAP_TTS_PROVIDER` | optional | `elevenlabs` (default when key and voice are set), `macos` (explicit approximation), `none` |
| `CLAP_MODEL` | optional | Claude model ID (default `claude-opus-4-6`) |
| `BRAVE_API_KEY` | optional | Web search ([api.search.brave.com](https://api.search.brave.com), free tier) |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` | optional | Email ([App Password](https://myaccount.google.com/apppasswords)) |
| `DEFAULT_EMAIL` | optional | Default recipient |
| `USER_NAME` | optional | Your name, used sparingly |
| `MORNING_BRIEFING_TIME` | optional | Daily briefing time (default `08:00`) |
| `WEB_PORT` | optional | HUD port (default `7777`) |
| `DB_PATH` | optional | Database file (default `clap.db`; an existing `jarvis.db` keeps being used) |

`.env` is git-ignored. No key is ever sent to the browser.

### 4. CLAP's voice

CLAP speaks with the ElevenLabs Voice Library voice **"Serafina – Sensual Temptress"**,
the voice in the reference recording. See [docs/VOICE.md](docs/VOICE.md) for the
analysis and the rights reasoning.

```bash
# after setting CLAP_TTS_API_KEY in .env
python -m voice find serafina
python -m voice add <public_owner_id> <voice_id>   # prints CLAP_TTS_VOICE_ID=...
python -m voice test "Hello. I am CLAP."
```

Without a configured voice, CLAP still runs and shows its replies, and says clearly
that voice output is unavailable.

---

## Running CLAP

```bash
source .venv/bin/activate

python clap.py --voice         # voice mode: say "CLAP" — HUD served at http://127.0.0.1:7777
python clap.py --voice --web   # voice mode and open the HUD in your browser
python clap.py --web           # HUD only (type commands), opens the browser
python clap.py                 # interactive terminal CLI
python clap.py "open Spotify"  # single command
python clap.py --briefing      # daily briefing
```

Options: `--mute` (no spoken replies), `--no-overlay`, `--no-browser`, `--no-hud`.

**Open the HUD:** <http://127.0.0.1:7777>. The text console for knowledge-base imports
and the task manifest is at <http://127.0.0.1:7777/console>.

**Frontend development:** run the backend (`python clap.py --web --no-browser`), then
`npm run dev` and open <http://localhost:5173> (API and event stream are proxied to :7777).

### Wake word

Say **"CLAP"** or **"Hey CLAP"**, wait for "Yes?", then give the command:

```
You:  "CLAP"
CLAP: "Yes?"
You:  "Open Spotify."
CLAP: "Opening Spotify."
```

Matching is whole-word ("clap", "Hey, CLAP", "C.L.A.P.", "klap"), and Whisper's sound
tags such as "(clapping)" or "[applause]" are ignored. Run `python debug_voice.py` to
see what your microphone picks up.

### HUD states

| State | HUD | Triggered by |
|---|---|---|
| STANDBY | CLAP ONLINE | ready; wake word armed |
| LISTENING | LISTENING... | wake word detected, command audio being captured |
| THINKING | PROCESSING... | Whisper transcribing / Claude reasoning |
| EXECUTING | EXECUTING ACTION... | a tool is running (tool + action shown) |
| SPEAKING | RESPONDING... | reply audio is playing |
| ERROR | SYSTEM ERROR | AI service unreachable, voice failure, mic failure |

The Predictive Arc responds through its public props (`speed`, `brightness`,
`saturation`). In STANDBY it runs exactly at the configured
`mode="dark" speed={1.00} hue={0} saturation={1.00} brightness={1.00}`.
Source verification: [docs/THREEUI_VERIFICATION.md](docs/THREEUI_VERIFICATION.md).

---

## macOS permissions

| Permission | Why | Where |
|---|---|---|
| Microphone | wake word and commands | System Settings → Privacy & Security → Microphone → allow your terminal (and, for autostart, the `.venv` Python) |
| Automation | closing apps via AppleScript ("Terminal wants to control Spotify") | System Settings → Privacy & Security → Automation |

Opening apps (`open -a`), browser automation (Playwright's own Chromium), and the HUD
need no extra permissions.

## Autostart

Only after CLAP works from Terminal (voice, HUD and Claude):

```bash
python autostart.py install          # voice mode + HUD on login
python autostart.py install --web    # HUD only
python autostart.py status | stop | start | uninstall
```

This also removes the old `com.jarvis.assistant` agent if present. Logs:
`logs/clap.log` (technical details), plus `logs/clap.out.log` and `logs/clap.err.log`.

## Optional integrations

Search, email and voice are optional. When one is missing CLAP starts normally and
says so when asked (e.g. "Search is not configured.").

## Tests

```bash
python -m unittest discover -s tests -t .
```

The suite covers the tool-use loop (scripted Claude responses), honest tool failures,
state sequencing, the SSE stream, the ElevenLabs request contract (mock server), the
voice pipeline (simulated microphone), app control and wake-word matching. Browser tests
run when `CLAP_TEST_BROWSER=1` is set (after `playwright install chromium`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| HUD says "has not been built yet" | `npm install && npm run build` |
| HUD shows LINK OFFLINE | Start the backend (`python clap.py --web` or `--voice`) and check `WEB_PORT` |
| "CLAP cannot reach the AI service." | Check `ANTHROPIC_API_KEY` and your network; details in `logs/clap.log` |
| "Voice output is currently unavailable." | Set `CLAP_TTS_API_KEY` / `CLAP_TTS_VOICE_ID`; run `python -m voice test` |
| Wake word never triggers | Microphone permission; try "Hey CLAP"; run `python debug_voice.py` |
| "Browser automation is unavailable" | `playwright install chromium` |
| "port 7777 is already in use" | Another CLAP is running (`python autostart.py stop`) or set `WEB_PORT` |
| Overlay error about tkinter | `brew install python-tk@3.12`, or use `--no-overlay` |
| First voice start is slow | Whisper `base.en` downloads once (~150 MB) |

## Tech stack

| Layer | Technology |
|---|---|
| Reasoning | Anthropic Claude via tool use (`anthropic` SDK) |
| Wake word & STT | `faster-whisper` (local) + `sounddevice` |
| Voice | ElevenLabs TTS (CLAP voice) → `afplay` |
| HUD | React 19 + TypeScript + Vite, ThreeUI `PredictiveArcCanvas` (`@designcodeio/threeui` 1.2.0) |
| Backend | Flask + server-sent events |
| Storage | SQLite + FTS5 |
| Browser automation | Playwright (Chrome if installed, else Chromium) |
| Autostart | macOS LaunchAgent |

## License

MIT
