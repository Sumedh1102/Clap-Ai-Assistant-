"""
CLAP agent — the reasoning loop, independent of the AI provider.

Loop:
  1. Append the user message → ask the model (ai.get_provider(), Gemini)
  2. If the model requests tools → run CLAP's tools → return real results → loop
  3. Otherwise → return the final text

The model only ever sees real tool results; failures are returned as failures.
Service problems surface as ClapAIError with a short, user-facing message;
technical details go to the log.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import ai
from ai import ClapAIError  # re-exported: session.py / clap.py import it from here
from config import config
from database import save_message
from tools.apps import close_application, open_application
from tools.briefing import get_daily_briefing
from tools.browser import (
    browser_click,
    browser_close,
    browser_current_url,
    browser_fill,
    browser_get_text,
    browser_navigate,
    browser_screenshot,
)
from tools.email_tool import send_email, send_email_with_attachment
from tools.knowledge_base import add_knowledge, search_knowledge
from tools.labels import tool_failed
from tools.search import search_web
from tools.tasks import add_task, delete_task, list_tasks, update_task

log = logging.getLogger("clap.agent")

# Tools are declared as neutral JSON Schema ({"name", "description", "parameters"});
# the provider adapter (ai/gemini.py) converts them to its function-calling format.

# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "add_task",
        "description": "Create a task in the user's local task list. Use when the user asks to add, remember to do, or schedule a to-do. Returns the new task ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short task title"},
                "description": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                "due_date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List tasks from the local task list, optionally filtered by status, priority, or due today. Use before updating or deleting tasks to find their IDs.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled", "all"]},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "all"]},
                "due_today": {"type": "boolean"},
            },
        },
    },
    {
        "name": "update_task",
        "description": "Update an existing task by ID (title, description, priority, status, due date). Mark a task done with status=completed.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]},
                "due_date": {"type": "string"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "delete_task",
        "description": "Permanently delete a task by ID. Irreversible: confirm with the user first unless they explicitly asked to delete that task.",
        "parameters": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "send_email",
        "description": "Send an email through the user's Gmail account. Confirm recipient, subject and body with the user before sending unless they gave all of them explicitly. Fails if Gmail is not configured.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "cc": {"type": "string"},
                "html": {"type": "boolean"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "send_email_with_attachment",
        "description": "Send an email with a local file attached through Gmail. Confirm before sending. Fails if Gmail is not configured or the file does not exist.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "attachment_path": {"type": "string"},
                "cc": {"type": "string"},
            },
            "required": ["to", "subject", "body", "attachment_path"],
        },
    },
    {
        "name": "search_web",
        "description": "Search the web (Brave Search) for current information, news, or facts you do not know. Fails with a clear message if search is not configured.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "count": {"type": "integer", "description": "Results to return (1-10)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "open_application",
        "description": "Open (launch) a macOS application by name, e.g. \"Spotify\" or \"Safari\". The result says whether it really opened; if not, tell the user it could not be opened and why.",
        "parameters": {
            "type": "object",
            "properties": {"app_name": {"type": "string"}},
            "required": ["app_name"],
        },
    },
    {
        "name": "close_application",
        "description": "Quit a running macOS application by name. Reports failure if the app is not running.",
        "parameters": {
            "type": "object",
            "properties": {"app_name": {"type": "string"}},
            "required": ["app_name"],
        },
    },
    {
        "name": "get_daily_briefing",
        "description": "Get today's task data (due today, overdue, high priority) for a daily briefing or when the user asks what is on their plate.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_current_datetime",
        "description": "Get the current local date, time and day of week. Use for any question involving today, now, or relative dates.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "search_knowledge",
        "description": (
            "Search the personal knowledge base for notes, documents, or imported "
            "conversations relevant to the query. Call this before answering factual "
            "questions or when context about past work may help."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms"},
                "n_results": {"type": "integer", "description": "Max results (default 5)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "add_knowledge",
        "description": "Save a note, fact, or preference to the user's long-term memory (knowledge base). Use when the user says remember/note that, or shares something worth keeping.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The text to save"},
                "title": {"type": "string", "description": "Short title for the entry"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "browser_navigate",
        "description": "Open a URL in CLAP's automated browser (Chrome if installed, otherwise Chromium). Use for opening or reading web pages. Returns the final URL and page title.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "browser_get_text",
        "description": "Read the visible text of the page currently open in the automated browser (optionally a CSS selector). Text is truncated to about 8000 characters.",
        "parameters": {
            "type": "object",
            "properties": {"selector": {"type": "string", "description": "CSS selector (default: body)"}},
        },
    },
    {
        "name": "browser_click",
        "description": "Click an element on the current browser page, by visible text (preferred) or CSS selector.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"},
            },
        },
    },
    {
        "name": "browser_fill",
        "description": "Type a value into an input on the current browser page (CSS selector). Set submit=true to press Enter. Confirm before submitting forms that send, buy, or change something.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "value": {"type": "string"},
                "submit": {"type": "boolean"},
            },
            "required": ["selector", "value"],
        },
    },
    {
        "name": "browser_screenshot",
        "description": "Save a screenshot of the current browser page to a file and return its path.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Optional save path"}},
        },
    },
    {
        "name": "browser_current_url",
        "description": "Get the URL and title of the page currently open in the automated browser.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "browser_close",
        "description": "Close CLAP's automated browser.",
        "parameters": {"type": "object", "properties": {}},
    },
]

# ── Tool dispatcher ───────────────────────────────────────────────────────────

def _get_current_datetime() -> dict:
    now = datetime.now()
    return {
        "datetime": now.isoformat(sep=" ", timespec="seconds"),
        "date": now.strftime("%A, %B %d %Y"),
        "time": now.strftime("%I:%M %p"),
        "iso_date": now.date().isoformat(),
    }


TOOL_HANDLERS: dict = {
    "add_task": add_task,
    "list_tasks": list_tasks,
    "update_task": update_task,
    "delete_task": delete_task,
    "send_email": send_email,
    "send_email_with_attachment": send_email_with_attachment,
    "search_web": search_web,
    "open_application": open_application,
    "close_application": close_application,
    "get_daily_briefing": get_daily_briefing,
    "get_current_datetime": _get_current_datetime,
    "search_knowledge": search_knowledge,
    "add_knowledge": add_knowledge,
    "browser_navigate": browser_navigate,
    "browser_get_text": browser_get_text,
    "browser_click": browser_click,
    "browser_fill": browser_fill,
    "browser_screenshot": browser_screenshot,
    "browser_current_url": browser_current_url,
    "browser_close": browser_close,
}


def run_tool(name: str, inputs: dict) -> dict:
    """Execute a tool and always return a dict (failures as {"success": False, "error": ...})."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"success": False, "error": f"Unknown tool: {name}"}
    try:
        result = handler(**(inputs or {}))
    except Exception as exc:
        log.exception("tool %s failed", name)
        return {"success": False, "error": f"Tool '{name}' failed: {exc}"}
    return result if isinstance(result, dict) else {"success": True, "result": result}


def dispatch_tool(name: str, inputs: dict) -> str:
    return json.dumps(run_tool(name, inputs), default=str)


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_BASE = """\
You are CLAP, a personal AI assistant running on the user's Mac. CLAP is an original \
assistant, not a character from any film or franchise. Your name is pronounced "clap". \
Do not mention the underlying AI model or provider unless the user explicitly asks.

VOICE & TONE
- Intelligent, calm, concise and natural, with a quietly futuristic precision.
- Lead with the answer or the action. No filler ("Certainly!", "I'd be delighted to...").
- Confirm actions in a few words: "Opening Spotify." / "Task added." / "Done."
- When something fails, say so plainly and, where useful, what would fix it.{address}

ACTIONS & HONESTY
- Use tools for anything that touches the computer, the web, tasks, email or memory. \
Never pretend an action happened.
- Only report an action as done after its tool result confirms success. If a tool result \
has "success": false or an "error", say it did not work (e.g. "Spotify could not be \
opened.") and give the reason in plain words.
- If an integration is not configured, say so briefly (e.g. "Search is not configured.").
- Confirm before consequential or irreversible actions unless the user explicitly asked \
for exactly that action with all details: sending email, deleting tasks or notes, \
submitting web forms, purchases, closing apps that may hold unsaved work. Opening apps, \
searching and reading need no confirmation.
- If a required detail is missing (recipient, date), ask one short question instead of guessing.

CAPABILITIES
- Task management: full CRUD via the local database.
- Email: draft and send via Gmail, with or without attachments.
- Web search: live results via Brave Search.
- Browser: navigate, click, fill forms, screenshot via an automated browser.
- App control: open and close macOS applications.
- Knowledge base: personal notes and imported documents you can search and save.
- Daily briefing: structured morning summary of tasks and priorities.

KNOWLEDGE BASE
- Before answering factual or personal questions, call search_knowledge to check if \
relevant context is stored.
- If the user shares information worth retaining ("remember that...", "note that..."), \
call add_knowledge proactively.

DAILY PLANNING
When asked about the day or schedule:
1. Call get_daily_briefing for task data.
2. Identify today's priorities and any overdue items.
3. Suggest a clear, prioritised order of work.
4. Offer to set task due dates or reminders if missing.

TOOL USE
- Always use tools rather than guessing.
- Chain tools logically: search before writing, list before updating."""

_VOICE_MODE = """

VOICE MODE ACTIVE
Replies are spoken aloud. Keep them to one to three short sentences. No markdown, lists, \
emoji or URLs. Write for the ear; spell out numbers and abbreviations where it helps."""


def _build_system(voice_mode: bool = False) -> str:
    address = ""
    if config.USER_NAME:
        address = f'\n- The user\'s name is {config.USER_NAME}. Use it sparingly.'
    prompt = _SYSTEM_BASE.replace("{address}", address)
    if voice_mode:
        prompt += _VOICE_MODE
    return prompt


# ── History helpers ───────────────────────────────────────────────────────────

def _as_text(content) -> str:
    """Stored content may be a string or a legacy list of {"type": "text"} blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
    return ""


def normalize_history(history: list[dict]) -> list[dict]:
    """
    Bring stored/legacy messages into the neutral format (see ai/base.py).
    Messages already in the neutral format pass through untouched.
    """
    out = []
    for msg in history:
        role = msg.get("role")
        if role in ("tool",) or msg.get("tool_calls") or msg.get("raw") is not None:
            out.append(msg)
        elif role in ("user", "assistant"):
            text = _as_text(msg.get("content"))
            if text:
                out.append({"role": role, "content": text})
    return out


def trim_history(history: list[dict], limit: int) -> list[dict]:
    """
    Keep at most `limit` messages, starting on a user turn so a tool call is
    never separated from its results.
    """
    trimmed = history[-limit:] if len(history) > limit else list(history)
    for i, msg in enumerate(trimmed):
        if msg.get("role") == "user":
            return trimmed[i:]
    return []


def _fallback_reply(tool_log: list[tuple[str, str | None]]) -> str:
    """
    Reply for the rare case where the model ends a turn without text: report
    the real outcome of the tools that ran, never an invented one.
    """
    if not tool_log:
        raise ClapAIError("The AI service returned an empty response. Please try again.")
    failures = [err for _, err in tool_log if err]
    if failures:
        return f"That did not work: {failures[-1]}"
    return "Done."


# ── Main chat function ────────────────────────────────────────────────────────

MAX_TOOL_ROUNDS = 12


def chat(
    user_message: str,
    conversation_history: list[dict],
    on_tool_call=None,
    voice_mode: bool = False,
    on_tool_result=None,
) -> tuple[str, list[dict]]:
    """
    Send a user message, run the tool-use loop, return (reply, updated_history).

    on_tool_call(name, inputs): called just before a tool runs.
    on_tool_result(name, inputs, result_dict): called after it finishes.
    voice_mode: if True, asks for short spoken replies.

    Raises ClapAIError if the AI service cannot be reached.
    """
    history = trim_history(normalize_history(conversation_history), config.HISTORY_LIMIT)
    history.append({"role": "user", "content": user_message})
    save_message("user", user_message)

    provider = ai.get_provider()
    system = _build_system(voice_mode)
    tool_log: list[tuple[str, str | None]] = []

    for _round in range(MAX_TOOL_ROUNDS):
        turn = provider.generate(system, history, TOOLS)

        if turn.tool_calls:
            history.append({"role": "assistant", "content": turn.text, "tool_calls": turn.tool_calls, "raw": turn.raw})
            results = []
            for call in turn.tool_calls:
                if on_tool_call:
                    on_tool_call(call.name, call.args)
                result = run_tool(call.name, call.args)
                failure = tool_failed(result)
                if failure:
                    log.info("tool %s reported failure: %s", call.name, failure)
                if on_tool_result:
                    on_tool_result(call.name, call.args, result)
                tool_log.append((call.name, failure))
                results.append({"id": call.id, "name": call.name, "content": result, "is_error": bool(failure)})
            history.append({"role": "tool", "results": results})
            continue

        text = turn.text
        if turn.finish == "blocked":
            text = text or "I can't help with that."
        elif turn.finish == "malformed":
            text = "I couldn't work out how to do that. Please try rephrasing."
        elif turn.finish == "max_tokens":
            text = (text + " …").strip() if text else "That reply was too long to finish."
        elif not text:
            text = _fallback_reply(tool_log)

        history.append({"role": "assistant", "content": text, "raw": turn.raw})
        save_message("assistant", text)
        return text, trim_history(history, config.HISTORY_LIMIT)

    log.warning("tool loop stopped after %d rounds", MAX_TOOL_ROUNDS)
    text = "I stopped after too many steps. Please narrow the request."
    history.append({"role": "assistant", "content": text})
    save_message("assistant", text)
    return text, trim_history(history, config.HISTORY_LIMIT)
