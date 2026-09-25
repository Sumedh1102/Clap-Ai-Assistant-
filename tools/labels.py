"""
Human-readable descriptions of tool calls for the HUD activity panel.

describe_tool_call("open_application", {"app_name": "Spotify"})
    → ("macOS App Control", "Opening Spotify")
"""

from __future__ import annotations


def _short(value: object, limit: int = 60) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


_CATEGORIES = {
    "add_task": "Tasks",
    "list_tasks": "Tasks",
    "update_task": "Tasks",
    "delete_task": "Tasks",
    "send_email": "Email",
    "send_email_with_attachment": "Email",
    "search_web": "Web Search",
    "open_application": "macOS App Control",
    "close_application": "macOS App Control",
    "get_daily_briefing": "Daily Briefing",
    "get_current_datetime": "Clock",
    "search_knowledge": "Memory",
    "add_knowledge": "Memory",
    "browser_navigate": "Browser",
    "browser_get_text": "Browser",
    "browser_click": "Browser",
    "browser_fill": "Browser",
    "browser_screenshot": "Browser",
    "browser_current_url": "Browser",
    "browser_close": "Browser",
}


def describe_tool_call(name: str, inputs: dict) -> tuple[str, str]:
    """Return (category label, present-tense action) for a tool call."""
    i = inputs or {}
    label = _CATEGORIES.get(name, name.replace("_", " ").title())
    actions = {
        "add_task": lambda: f"Adding task: {_short(i.get('title'))}",
        "list_tasks": lambda: "Reviewing tasks",
        "update_task": lambda: f"Updating task #{i.get('task_id')}",
        "delete_task": lambda: f"Deleting task #{i.get('task_id')}",
        "send_email": lambda: f"Sending email to {_short(i.get('to'))}",
        "send_email_with_attachment": lambda: f"Sending email with attachment to {_short(i.get('to'))}",
        "search_web": lambda: f"Searching: {_short(i.get('query'))}",
        "open_application": lambda: f"Opening {_short(i.get('app_name'))}",
        "close_application": lambda: f"Closing {_short(i.get('app_name'))}",
        "get_daily_briefing": lambda: "Preparing briefing",
        "get_current_datetime": lambda: "Checking the time",
        "search_knowledge": lambda: f"Recalling: {_short(i.get('query'))}",
        "add_knowledge": lambda: f"Remembering: {_short(i.get('title') or i.get('content'))}",
        "browser_navigate": lambda: f"Opening {_short(i.get('url'))}",
        "browser_get_text": lambda: "Reading page",
        "browser_click": lambda: f"Clicking {_short(i.get('text') or i.get('selector'))}",
        "browser_fill": lambda: f"Filling {_short(i.get('selector'))}",
        "browser_screenshot": lambda: "Capturing page",
        "browser_current_url": lambda: "Checking current page",
        "browser_close": lambda: "Closing browser",
    }
    make = actions.get(name)
    return label, (make() if make else label)


def tool_failed(result: object) -> str | None:
    """
    Return a short failure reason if a tool result reports failure, else None.
    Tools signal failure with {"success": False, ...} or an "error" key.
    """
    if not isinstance(result, dict):
        return None
    if result.get("success") is False or "error" in result:
        return _short(result.get("error") or result.get("message") or "Tool reported failure", 160)
    return None
