"""
Helpers for reading / writing test-chamber.json.
"""

import json
import os
import config
from teststate import is_test_mode, get_test_chamber, set_test_chamber

DEFAULT_CHAMBER = {
    f"test{i}": {"code": None, "accepted_by": None}
    for i in range(1, 6)
}


def _path() -> str:
    return config.CHAMBER_FILE


def load_chamber() -> dict:
    """Load the chamber data, creating the file with defaults if missing."""
    if is_test_mode():
        return get_test_chamber().copy()
    p = _path()
    if not os.path.exists(p):
        save_chamber(DEFAULT_CHAMBER)
        return DEFAULT_CHAMBER.copy()
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_chamber(data: dict) -> None:
    """Persist chamber data to disk (or memory in test mode)."""
    if is_test_mode():
        set_test_chamber(data)
        return
    p = _path()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_next_available_slot(data: dict) -> str | None:
    """Return the key of the first empty slot, or None if all full."""
    for key in sorted(data.keys()):
        if data[key]["code"] is None:
            return key
    return None


def set_slot(slot_key: str, code: str, accepted_by: str) -> bool:
    """
    Write a code + acceptor into a slot.
    Returns False if the payload exceeds the char limit.
    """
    payload_len = len(code) + len(accepted_by)
    if payload_len > config.SLOT_CHAR_LIMIT:
        return False

    data = load_chamber()
    data[slot_key] = {"code": code, "accepted_by": accepted_by}
    save_chamber(data)
    return True


def clear_slot(slot_key: str) -> None:
    """Reset a slot back to empty."""
    data = load_chamber()
    if slot_key in data:
        data[slot_key] = {"code": None, "accepted_by": None}
        save_chamber(data)


def get_filled_slots(data: dict) -> list[tuple[str, dict]]:
    """Return a list of (key, slot_data) for slots that have a code."""
    return [(k, v) for k, v in sorted(data.items()) if v["code"] is not None]
