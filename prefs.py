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

PATH = os.environ.get("ANCS_PREFS_PATH") or os.path.join(paths.DATA_DIR,
                                                         "prefs.json")
# ANCS_PREFS_PATH exists so a test can point preferences at a scratch file.
# Without it, any test that drives the real Settings controls writes to the
# user's own prefs.json - which is how a theme choice got silently replaced
# during development. Tests set it before importing prefs.

DEFAULTS = {
    "toast_opacity": 1.0,        # 0.5 - 1.0
    "theme_mode": "dark",        # "dark" | "light"

    # --- notification rules (see rules.py for precedence) ---
    # "off" | "allowlist" | "blocklist"
    "app_filter_mode": "off",
    "app_allowlist": [],         # bundle ids
    "app_blocklist": [],         # bundle ids
    "priority_apps": [],         # bundle ids that ignore quiet hours
    "quiet_enabled": False,
    "quiet_start": "22:00",
    "quiet_end": "07:00",
    # [{"pattern": word, "action": "show"|"silent"|"drop"}], first match wins.
    # `pattern` is a plain substring, matched case-insensitively.
    "keyword_rules": [],

    # --- history ---
    # Off means nothing is written to feed.db at all. The in-memory feed
    # still works for the current session; it simply does not survive a
    # restart. Turning it off does NOT delete what is already stored.
    "save_history": True,

    "snooze_minutes": 10,

    # Which monitor desktop banners appear on: "cursor" (the screen the
    # pointer is on), "primary", or a QScreen name. Falls back safely if a
    # named screen is unplugged.
    "toast_screen": "cursor",
}

_lock = threading.Lock()
_values: dict = dict(DEFAULTS)


def _load() -> None:
    """
    Read prefs.json, filling in defaults for anything missing.

    Logs which path was used and whether a file was found. Silence here is
    expensive: if the file goes missing every setting silently reverts to
    its default, which looks exactly like "the app forgot my choice" and is
    very hard to tell apart from a bug in the setting itself.
    """
    try:
        with open(PATH, "r", encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            known = {k: v for k, v in stored.items() if k in DEFAULTS}
            _values.update(known)
            log(f"loaded {len(known)} preference(s) from {PATH}", "app")
            unknown = set(stored) - set(DEFAULTS)
            if unknown:
                log(f"ignoring unknown preference(s): {sorted(unknown)}", "app")
            return
        log(f"{PATH} is not a JSON object; using defaults", "app")
    except FileNotFoundError:
        log(f"no preferences file at {PATH}; starting from defaults", "app")
    except (OSError, ValueError) as exc:
        log(f"could not read {PATH} ({exc}); using defaults", "app")


_load()


def get(key: str):
    with _lock:
        return _values.get(key, DEFAULTS.get(key))


def set(key: str, value) -> bool:                        # noqa: A001
    """
    Store one preference and write the file. Returns whether it persisted.

    An unknown key is rejected rather than stored, because DEFAULTS is also
    the schema - accepting one would write a value that _load() then
    silently discards on the next start, which is worse than refusing it.
    """
    if key not in DEFAULTS:
        log(f"refusing to set unknown preference {key!r} "
            f"(add it to prefs.DEFAULTS first)", "app")
        return False
    with _lock:
        _values[key] = value
        snapshot = dict(_values)
    try:
        os.makedirs(paths.DATA_DIR, exist_ok=True)
        # Written whole rather than patched, so a crash mid-write cannot
        # leave a half-valid file that _load() would accept.
        with open(PATH, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2)
        return True
    except OSError as exc:
        log(f"could not save preferences: {exc}", "app")
        return False
