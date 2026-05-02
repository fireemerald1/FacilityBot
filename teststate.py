"""
Global test-mode state.

Kept dependency-free to avoid circular imports.
"""

_test_mode = False
_test_chamber = None
_test_messages = []


def is_test_mode() -> bool:
    return _test_mode


def enable_test_mode() -> None:
    global _test_mode, _test_chamber, _test_messages
    _test_mode = True
    _test_chamber = {
        f"test{i}": {"code": None, "accepted_by": None}
        for i in range(1, 6)
    }
    _test_messages = []


def disable_test_mode() -> None:
    global _test_mode, _test_chamber, _test_messages
    _test_mode = False
    _test_chamber = None
    _test_messages = []


def get_test_chamber() -> dict | None:
    return _test_chamber


def set_test_chamber(data: dict) -> None:
    global _test_chamber
    _test_chamber = data


def track_test_message(msg) -> None:
    _test_messages.append(msg)


def get_test_messages() -> list:
    return list(_test_messages)
