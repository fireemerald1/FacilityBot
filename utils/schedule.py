"""
Schedule helpers — shared between the scheduler cog and work-system cogs.
"""

import json
import os
from datetime import datetime, timezone
from teststate import is_test_mode

from config import (
    ACTIVE_DAYS,
    ACTIVE_START_HOUR,
    ACTIVE_END_HOUR,
    SCHEDULE_FILE,
)


def _state_path() -> str:
    """Return the absolute path to schedule-state.json."""
    return SCHEDULE_FILE


def load_schedule_state() -> dict:
    p = _state_path()
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_schedule_state(data: dict) -> None:
    p = _state_path()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_within_active_window() -> bool:
    """Return True if right now is inside the Sat/Sun 05:00–17:00 UTC window."""
    if is_test_mode():
        return True
    now = datetime.now(timezone.utc)
    return now.weekday() in ACTIVE_DAYS and ACTIVE_START_HOUR <= now.hour < ACTIVE_END_HOUR


def iso_week(dt: datetime) -> str:
    """Return 'YYYY-WNN' ISO-week string for *dt*."""
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"
