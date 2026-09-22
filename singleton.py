"""
singleton.py - one running copy, not several.

Two instances are worse than a confusing window count. Both bond to the same
phone, and BLE does not share: the second link fights the first exactly the
way Phone Link does, which is the whole reason this app asks you to disable
Phone Link's autostart. Two instances also write the same feed.db and the
same prefs.json, so a setting changed in one is silently overwritten by the
other.

A named mutex rather than a lock file. A lock file survives a crash and then
lies about the app still running, which means shipping stale-lock detection
by pid, and pids get reused. The kernel releases a mutex when the owning
process dies, however it dies, so there is no stale state to reason about.

The name carries the Local\\ prefix, scoping it to the session: two signed-in
users each get their own instance, which is right - they have separate
LOCALAPPDATA, separate settings, and possibly separate phones.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import paths
from applog import log

MUTEX_NAME = "Local\\ANCSNotifier.SingleInstance"
WINDOW_TITLE = "iPhone Connect"      # matches Dashboard.setWindowTitle

_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9

# Held for the life of the process. Module-level on purpose: if this went out
# of scope the handle would close and the guard would stop working silently.
_handle = None


def acquire() -> bool:
    """
    True if this process is the first instance.

    Never raises. If the mutex cannot be created at all - a locked-down
    session, a non-Windows host - the app is allowed to start rather than
    refusing to run over a guard that is only a convenience.
    """
    global _handle
    if _handle is not None:
        return True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                          wintypes.LPCWSTR]
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        error = ctypes.get_last_error()
    except (OSError, AttributeError) as exc:
        log(f"single-instance guard unavailable ({exc}); starting anyway",
            "app")
        return True

    if not handle:
        log("could not create the single-instance mutex; starting anyway",
            "app")
        return True
    if error == _ERROR_ALREADY_EXISTS:
        # The handle is left for the owning process; this one is the second.
        return False
    _handle = handle
    return True


def raise_existing() -> bool:
    """
    Bring the running instance's window to the front. True if one was found.

    Done by window title, which is the only handle a separate process has on
    it without a pipe or a socket. If the first instance is sitting in the
    tray with no window shown there is nothing to raise, and that is reported
    rather than hidden, so a user who double-clicked the shortcut and saw
    nothing has something in the log to read.
    """
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.FindWindowW.restype = wintypes.HWND
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, _SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except (OSError, AttributeError):
        return False


def release() -> None:
    """Explicit release, for completeness. Windows does this on process exit
    anyway, which is the point of using a mutex."""
    global _handle
    if _handle is None:
        return
    try:
        ctypes.WinDLL("kernel32").CloseHandle(_handle)
    except (OSError, AttributeError):
        pass
    _handle = None


def already_running_message() -> str:
    return f"{paths.APP_TITLE} is already running."
