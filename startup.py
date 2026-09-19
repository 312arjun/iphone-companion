"""
startup.py - "Start with Windows", via the per-user Run key.

HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run needs no admin rights
and no scheduled task, and Windows' own Startup apps list can disable it,
which is where people look first.

Running from source it registers pythonw.exe (no console window); frozen it
registers the exe itself.
"""

from __future__ import annotations

import os
import sys

from applog import log

VALUE_NAME = "ANCSNotifier"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

BASE = os.path.dirname(os.path.abspath(__file__))


def _command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    runner = pythonw if os.path.exists(pythonw) else sys.executable
    return f'"{runner}" "{os.path.join(BASE, "qt_main.py")}"'


def available() -> bool:
    try:
        import winreg                                    # noqa: F401
        return True
    except ImportError:
        return False


def is_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except (ImportError, FileNotFoundError, OSError):
        return False


def set_enabled(enabled: bool) -> bool:
    """Returns the state actually achieved, so the UI can stay honest."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ,
                                  _command())
                log("will start with Windows", "app")
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                    log("will not start with Windows", "app")
                except FileNotFoundError:
                    pass
        return enabled
    except Exception as exc:
        log(f"could not change startup setting: {exc}", "app")
        return is_enabled()
