"""
desktop.py - the "Desktop shortcut" setting.

A .lnk is a COM object, and pywin32 is not a dependency, so the shortcut is
created through PowerShell's WScript.Shell. That also solves a second
problem for free: the Desktop is not always %USERPROFILE%\\Desktop. With
OneDrive folder backup switched on it moves under the OneDrive folder, and
writing to the literal path would silently put the shortcut somewhere the
user cannot see. [Environment]::GetFolderPath('Desktop') returns wherever it
actually is.

Running from source the shortcut points at pythonw.exe (no console window)
with qt_main.py as its argument; frozen, it points at the exe.
"""

from __future__ import annotations

import os
import subprocess
import sys

import paths
from applog import log

NAME = "iPhone Companion"
BASE = os.path.dirname(os.path.abspath(__file__))

# Frozen apps have no console, so a visible PowerShell window would flash on
# screen every time this runs.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _powershell(script: str) -> tuple[bool, str]:
    """Run a snippet, returning (ok, stdout-or-error). Never raises."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=20,
            creationflags=_NO_WINDOW)
        if result.returncode != 0:
            return False, (result.stderr or "").strip()
        return True, (result.stdout or "").strip()
    except Exception as exc:
        return False, str(exc)


def _target() -> tuple[str, str]:
    """(executable, arguments) for the shortcut."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    runner = pythonw if os.path.exists(pythonw) else sys.executable
    return runner, '"%s"' % os.path.join(BASE, "qt_main.py")


def folder() -> str:
    """The real Desktop, which OneDrive backup may have relocated."""
    ok, out = _powershell("[Environment]::GetFolderPath('Desktop')")
    if ok and out:
        return out
    return os.path.join(os.path.expanduser("~"), "Desktop")


def path() -> str:
    return os.path.join(folder(), NAME + ".lnk")


def exists() -> bool:
    return os.path.exists(path())


def create() -> bool:
    """Make (or refresh) the shortcut. Returns whether it is there after."""
    executable, arguments = _target()
    icon = paths.bundled("assets", "app.ico")
    if not os.path.exists(icon):
        icon = executable

    # Single-quoted PowerShell strings: only ' needs escaping, and doubling
    # it is the escape. Paths with spaces, &, or $ are then literal, which
    # building a double-quoted command line would not guarantee.
    def q(value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(%s);"
        "$s.TargetPath = %s;"
        "$s.Arguments = %s;"
        "$s.WorkingDirectory = %s;"
        "$s.IconLocation = %s;"
        "$s.Description = %s;"
        "$s.Save()" % (q(path()), q(executable), q(arguments),
                       q(BASE if not getattr(sys, "frozen", False)
                         else os.path.dirname(executable)),
                       q(icon), q("Mirror your iPhone to this PC"))
    )
    ok, message = _powershell(script)
    if not ok:
        log(f"could not create desktop shortcut: {message}", "app")
        return exists()
    log(f"desktop shortcut created at {path()}", "app")
    return exists()


def remove() -> bool:
    """Delete it. Returns whether it is gone."""
    try:
        os.remove(path())
        log("desktop shortcut removed", "app")
    except FileNotFoundError:
        pass
    except OSError as exc:
        log(f"could not remove desktop shortcut: {exc}", "app")
    return not exists()


def set_enabled(enabled: bool) -> bool:
    """Returns the state actually achieved, so the UI can stay honest."""
    return create() if enabled else not remove()
