"""Monotonic, lexicographically-sortable IDs with opencode-style prefixes.

The TUI orders messages/parts by binary-searching their string ids, so ids must
sort in creation order. Fixed-width ``<ms><counter>`` guarantees that.
"""

import itertools
import threading
import time

_counter = itertools.count()
_lock = threading.Lock()


def _new(prefix: str) -> str:
    with _lock:
        n = next(_counter)
    return f"{prefix}_{int(time.time() * 1000):013d}{n:09d}"


def session_id() -> str:
    return _new("ses")


def message_id() -> str:
    return _new("msg")


def part_id() -> str:
    return _new("prt")


def call_id() -> str:
    return _new("call")


def event_id() -> str:
    return _new("evt")
