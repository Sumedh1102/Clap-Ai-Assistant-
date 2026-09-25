"""
CLAP agent — Claude reasoning with tool use.

Loop:
  1. Append user message → call Claude
  2. If stop_reason == "tool_use" → run tools → feed results back → loop
  3. Otherwise → return the final text

Failures of the AI service surface as ClapAIError with a short, user-facing
message; technical details go to the log, never to the user.
"""

import json
import logging
from datetime import datetime

import anthropic

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

# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "add_task",
        "description": "Add a new task to the task manager.",
        "input_schema": {
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
        "description": "List tasks with optional filters.",
        "input_schema": {
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
        "description": "Update an existing task.",
        "input_schema": {
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
        "description": "Permanently delete a task by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "send_email",
        "description": "Send an email via Gmail.",
        "input_schema": {
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
        "description": "Send an email with a local file attached.",
        "input_schema": {
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
        "description": "Search the web with Brave Search for current information.",
        "input_schema": {
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
        "description": "Open/launch an application on the computer.",
        "input_schema": {
            "type": "object",
            "properties": {"app_name": {"type": "string"}},
            "required": ["app_name"],
        },
    },
    {
        "name": "close_application",
        "description": "Quit/close a running application.",
        "input_schema": {
            "type": "object",
            "properties": {"app_name": {"type": "string"}},
            "required": ["app_name"],
        },
    },
    {
        "name": "get_daily_briefing",
        "description": "Retrieve task and time data for the daily morning briefing.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_current_datetime",
        "description": "Get the current date, time, and day of week.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_knowledge",
        "description": (
            "Search the personal knowledge base for notes, documents, or imported "
            "conversations relevant to the query. Call this before answering factual "
            "questions or when context about past work may help."
        ),
        "input_schema": {
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
        "description": "Save a note, fact, or piece of information to the knowledge base for future reference.",
        "input_schema": {
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
        "description": "Open a URL in the automated browser (Chrome if installed, otherwise Chromium).",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "browser_get_text",
        "description": "Extract visible text from the current browser page.",
        "input_schema": {
            "type": "object",
            "properties": {"selector": {"type": "string", "description": "CSS selector (default: body)"}},
        },
    },
    {
        "name": "browser_click",
        "description": "Click an element on the current page by CSS selector or visible text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"},
            },
        },
    },
    {
        "name": "browser_fill",
        "description": "Fill a text input on the current page.",
        "input_schema": {
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
        "description": "Take a screenshot of the current browser page.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Optional save path"}},
        },
    },
    {
        "name": "browser_current_url",
        "description": "Get the current browser URL and page title.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "browser_close",
        "description": "Close the automated browser window.",
        "input_schema": {"type": "object", "properties": {}},
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
assistant, not a character from any film or franchise. Your name is pronounced "clap".

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


# ── Errors ────────────────────────────────────────────────────────────────────

class ClapAIError(RuntimeError):
    """The AI service could not produce a reply. `user_message` is safe to show/speak."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


def _to_clap_error(exc: Exception) -> ClapAIError:
    """Map SDK exceptions (most specific first) to user-facing messages."""
    if isinstance(exc, anthropic.AuthenticationError):
        return ClapAIError("CLAP cannot reach the AI service. The Anthropic API key was rejected.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return ClapAIError("CLAP cannot reach the AI service. The API key is not permitted to use this model.")
    if isinstance(exc, anthropic.NotFoundError):
        return ClapAIError(f"CLAP cannot reach the AI service. The model {config.MODEL} was not found.")
    if isinstance(exc, anthropic.RateLimitError):
        return ClapAIError("The AI service is rate limiting CLAP. Try again in a moment.")
    if isinstance(exc, anthropic.BadRequestError):
        return ClapAIError("The AI service rejected the request.")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:
            return ClapAIError("The AI service is temporarily unavailable. Try again in a moment.")
        return ClapAIError("The AI service returned an error.")
    if isinstance(exc, anthropic.APIConnectionError):
        return ClapAIError("CLAP cannot reach the AI service.")
    return ClapAIError("CLAP cannot reach the AI service.")


# ── History helpers ───────────────────────────────────────────────────────────

def _has_tool_result(content) -> bool:
    if not isinstance(content, list):
        return False
    return any(
        (b.get("type") if isinstance(b, dict) else getattr(b, "type", None)) == "tool_result"
        for b in content
    )


def trim_history(history: list[dict], limit: int) -> list[dict]:
    """
    Keep at most `limit` messages, starting on a plain user turn so no
    tool_result is left without the tool_use that produced it.
    """
    trimmed = history[-limit:] if len(history) > limit else list(history)
    for i, msg in enumerate(trimmed):
        if msg.get("role") == "user" and not _has_tool_result(msg.get("content")):
            return trimmed[i:]
    return []


def _text_of(content) -> str:
    parts = []
    for b in content:
        if getattr(b, "type", None) == "text" and getattr(b, "text", ""):
            parts.append(b.text)
    return "\n\n".join(parts).strip()


# ── Main chat function ────────────────────────────────────────────────────────

_client: "anthropic.Anthropic | None" = None
MAX_TOOL_ROUNDS = 12


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=60.0, max_retries=2)
    return _client


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
    voice_mode: if True, instructs Claude to reply in short spoken sentences.

    Raises ClapAIError if the AI service cannot be reached.
    """
    history = trim_history(list(conversation_history), config.HISTORY_LIMIT)
    history.append({"role": "user", "content": user_message})
    save_message("user", user_message)
    client = _get_client()

    for _round in range(MAX_TOOL_ROUNDS):
        try:
            response = client.messages.create(
                model=config.MODEL,
                max_tokens=config.MAX_TOKENS,
                system=_build_system(voice_mode),
                tools=TOOLS,
                messages=history,
            )
        except anthropic.APIError as exc:
            log.error("Claude request failed: %r", exc)
            raise _to_clap_error(exc) from exc

        if response.stop_reason == "tool_use":
            history.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if on_tool_call:
                    on_tool_call(block.name, block.input)
                result = run_tool(block.name, block.input)
                failure = tool_failed(result)
                if failure:
                    log.info("tool %s reported failure: %s", block.name, failure)
                if on_tool_result:
                    on_tool_result(block.name, block.input, result)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                    **({"is_error": True} if failure else {}),
                })
            history.append({"role": "user", "content": tool_results})
            continue

        text = _text_of(response.content)
        if response.stop_reason == "refusal" and not text:
            text = "I can't help with that."
        elif response.stop_reason == "max_tokens":
            text = (text + " …").strip() if text else "That reply was too long to finish."
        elif response.stop_reason not in ("end_turn", "stop_sequence"):
            log.warning("unexpected stop_reason: %s", response.stop_reason)

        # Only text is kept for finished turns: never leave an unanswered tool_use behind.
        final_content = [{"type": "text", "text": text}] if text else []
        if final_content:
            history.append({"role": "assistant", "content": final_content})
            save_message("assistant", final_content)
        return text, trim_history(history, config.HISTORY_LIMIT)

    log.warning("tool loop stopped after %d rounds", MAX_TOOL_ROUNDS)
    text = "I stopped after too many steps. Please narrow the request."
    history.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
    save_message("assistant", [{"type": "text", "text": text}])
    return text, trim_history(history, config.HISTORY_LIMIT)
