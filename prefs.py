"""
prefs.py - small persisted settings.

Anything the user changes in the Settings page that should survive a restart
lives here, in %LOCALAPPDATA%\\ANCSNotifier\\prefs.json. Deliberately tiny:
plain JSON, no schema, defaults filled in on read, so a missing or corrupt
file is never fatal.
"""

from __future__ import annotations

import json
import os
import threading

import paths
from applog import log

PATH = os.path.join(paths.DATA_DIR, "prefs.json")

DEFAULTS = {
    "toast_opacity": 1.0,        # 0.5 - 1.0
}

_lock = threading.Lock()
_values: dict = dict(DEFAULTS)


def _load() -> None:
    try:
        with open(PATH, "r", encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            _values.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass


_load()


def get(key: str):
    with _lock:
        return _values.get(key, DEFAULTS.get(key))


def set(key: str, value) -> None:                        # noqa: A001
    if key not in DEFAULTS:
        return
    with _lock:
        _values[key] = value
        snapshot = dict(_values)
    try:
        os.makedirs(paths.DATA_DIR, exist_ok=True)
        with open(PATH, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2)
    except OSError as exc:
        log(f"could not save preferences: {exc}", "app")
