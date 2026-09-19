"""
paths.py - where runtime data lives.

Running from source, everything stays next to the scripts, which is handy for
poking at config.json and the log by hand.

Running as a frozen exe, sys._MEIPASS is a temp folder that PyInstaller wipes
on exit, so writable state has to go somewhere permanent:
    %LOCALAPPDATA%\\ANCSNotifier\\
"""

from __future__ import annotations

import os
import sys

APP_NAME = "ANCSNotifier"
APP_TITLE = "iPhone Companion"
APP_VERSION = "1.2.0"          # keep installer.iss MyAppVersion in step
FROZEN = bool(getattr(sys, "frozen", False))


def _resolve_data_dir() -> str:
    if FROZEN:
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(root, APP_NAME)
    else:
        path = os.path.dirname(os.path.abspath(__file__))
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = os.path.expanduser("~")
    return path


DATA_DIR = _resolve_data_dir()
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LOG_PATH = os.path.join(DATA_DIR, "ancs_notifier.log")
ICON_CACHE = os.path.join(DATA_DIR, "icon_cache")


def bundled(*parts) -> str:
    """
    A read-only file shipped with the app.

    PyInstaller unpacks --add-data into sys._MEIPASS, which is NOT where
    __file__ points for a onedir build, so assets have to be resolved through
    this rather than relative to the module.
    """
    root = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.abspath(__file__))
    return os.path.join(root, *parts)
