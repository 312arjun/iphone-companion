"""
applog.py - one small logger for the whole app.

Replaces the scattered print()s and banner art. Every line is timestamped,
tagged, and kept in a ring buffer so the GUI can show a live log without
re-reading the file.

    from applog import log
    log("Listening", "ble")
    log(f"battery {pct}%", "ble", debug=True)     # only with ANCS_DEBUG=1
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque

DEBUG = os.environ.get("ANCS_DEBUG", "") not in ("", "0", "false", "False")
BUFFER = deque(maxlen=400)
_lock = threading.Lock()


def log(message: str, tag: str = "app", debug: bool = False) -> None:
    """Print one line. debug=True lines are hidden unless ANCS_DEBUG=1."""
    if debug and not DEBUG:
        return
    stamp = time.strftime("%H:%M:%S")
    line = f"{stamp}  {tag:<5} {message}"
    with _lock:
        BUFFER.append((time.time(), tag, message))
    try:
        print(line)
        sys.stdout.flush()
    except Exception:
        pass


def recent(limit: int = 100):
    with _lock:
        return list(BUFFER)[-limit:]
