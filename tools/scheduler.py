"""
Background task scheduler.

Runs a daemon thread that fires events at configured times:
  - Daily briefing at MORNING_BRIEFING_TIME
  - Hourly overdue-task reminder check
"""

from __future__ import annotations

import threading
import time
from datetime import date
from typing import Callable

try:
    import schedule  # type: ignore
    _SCHEDULE_OK = True
except ImportError:
    _SCHEDULE_OK = False

from config import config
from tools.tasks import list_tasks

_thread: "threading.Thread | None" = None
_stop = threading.Event()


def start_scheduler(on_event: Callable[[str], None]) -> None:
    """
    Start the background scheduler.
    `on_event(message)` is called on the main thread via a queue
    (callers should poll get_pending_events() each loop iteration).
    """
    global _thread, _stop

    if not _SCHEDULE_OK:
        return  # silently skip if schedule not installed

    _stop.clear()

    briefing_time = config.MORNING_BRIEFING_TIME or "08:00"

    schedule.every().day.at(briefing_time).do(
        lambda: on_event("Give me my daily briefing.")
    )
    schedule.every().hour.do(lambda: _check_overdue(on_event))

    def _run() -> None:
        while not _stop.is_set():
            schedule.run_pending()
            time.sleep(20)

    _thread = threading.Thread(target=_run, name="clap-scheduler", daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    _stop.set()
    schedule.clear()


def _check_overdue(on_event: Callable[[str], None]) -> None:
    today = date.today().isoformat()
    result = list_tasks(status="pending")
    overdue = [
        t for t in result["tasks"]
        if t.get("due_date") and t["due_date"] < today
    ]
    if overdue:
        titles = ", ".join(t["title"] for t in overdue[:3])
        suffix = f" and {len(overdue) - 3} more" if len(overdue) > 3 else ""
        on_event(
            f"Reminder: {len(overdue)} overdue task(s): {titles}{suffix}. "
            "Would you like to review them?"
        )
