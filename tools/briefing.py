"""Daily briefing data — gathers tasks and time context for the AI to narrate."""

from datetime import date, datetime

from tools.tasks import list_tasks


def get_daily_briefing() -> dict:
    today = date.today().isoformat()
    now = datetime.now()

    hour = now.hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    all_tasks = list_tasks(status="all")["tasks"]

    pending = [t for t in all_tasks if t["status"] in ("pending", "in_progress")]
    due_today = [t for t in pending if t.get("due_date") == today]
    overdue = [
        t for t in pending
        if t.get("due_date") and t["due_date"] < today
    ]
    completed_today = [
        t for t in all_tasks
        if t["status"] == "completed" and (t.get("updated_at") or "").startswith(today)
    ]

    high_priority = [t for t in pending if t["priority"] == "high"]

    return {
        "greeting": greeting,
        "date": now.strftime("%A, %B %d %Y"),
        "time": now.strftime("%I:%M %p"),
        "stats": {
            "total_pending": len(pending),
            "due_today": len(due_today),
            "overdue": len(overdue),
            "completed_today": len(completed_today),
            "high_priority": len(high_priority),
        },
        "due_today_tasks": due_today,
        "overdue_tasks": overdue,
        "high_priority_tasks": high_priority[:5],
    }
