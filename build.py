"""
build.py - package the app into a standalone Windows executable.

    python build.py              -> dist\\iPhoneCompanion\\ (folder build)
    python build.py --onefile    -> a single portable exe
    python build.py --installer  -> folder build + Setup exe via Inno Setup

Needs: pip install pyinstaller
Optional (for --installer): Inno Setup 6  https://jrsoftware.org/isdl.php

The entry point is qt_main.py. It used to be tray_app.py, which is the old
Tkinter/pystray build - freezing that produced an exe with a tray icon and no
window at all, because the Qt dashboard was never part of the bundle.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "iPhoneCompanion"
ENTRY = os.path.join(BASE, "qt_main.py")
ASSETS = os.path.join(BASE, "assets")
ICO = os.path.join(ASSETS, "app.ico")
DIST = os.path.join(BASE, "dist")

# Imported by name at runtime, or pulled in late enough that PyInstaller's
# analysis can miss them.
OUR_MODULES = (
    "ams", "ancs", "app_ble", "appicon", "applog", "calls", "dashboard",
    "icons", "lyrics", "notify", "otp", "paths", "prefs", "qt_toast",
    "shortcuts", "simulate", "spotify", "startup", "status", "store",
    "theme", "vicons", "widgets",
)

INNO_CANDIDATES = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def preflight() -> None:
    """
    PyInstaller can only bundle what it can import, so it has to live in the
    same interpreter as the runtime dependencies. This catches the classic
    Windows mess of `pip` and `python` resolving to different installs.
    """
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    print(f"python      {sys.version.split()[0]}  ({sys.executable})")
    print(f"virtualenv  {'yes' if in_venv else 'NO'}")

    required = {
        "PyInstaller": "pyinstaller",
        "PySide6": "pyside6",
        "PIL": "pillow",
        "bleak": "bleak",
    }
    missing = []
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        print("\nMissing from THIS interpreter: " + ", ".join(missing))
        print("\nActivate the venv and install with `python -m pip`:\n")
        print("    .venv\\Scripts\\activate")
        print("    python -m pip install -r requirements.txt pyinstaller")
        print("    python build.py --installer")
        sys.exit(1)

    if not os.path.exists(ICO):
        print(f"\nNo icon at {ICO}")
        print('Run:  python make_icon.py "path\\to\\icon.png"')
        sys.exit(1)
    print(f"icon        {ICO}")


def pyinstaller_args(onefile: bool) -> list[str]:
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", APP_NAME,
        "--noconsole",                      # no console window, ever
        "--icon", ICO,

        # the artwork is loaded at runtime by appicon.py
        "--add-data", f"{ASSETS}{os.pathsep}assets",

        # Qt: plugins and DLLs are resolved dynamically
        "--collect-all", "PySide6",

        # bleak picks its backend at runtime; winrt is a namespace package
        # split across a dozen distributions. Neither is statically visible.
        "--collect-submodules", "bleak",
        "--collect-all", "winrt",

        # macOS / Linux backends will never import on Windows
        "--exclude-module", "bleak.backends.corebluetooth",
        "--exclude-module", "bleak.backends.bluezdbus",

        # the superseded Tkinter banner path, not used by qt_main
        "--exclude-module", "macos_toast",
        "--exclude-module", "tray_app",
        "--exclude-module", "pystray",
        "--paths", BASE,
    ]
    for module in OUR_MODULES:
        args += ["--hidden-import", module]
    args.append("--onefile" if onefile else "--onedir")
    args.append(ENTRY)
    return args


def run_pyinstaller(onefile: bool) -> None:
    print(f"\npyinstaller ({'onefile' if onefile else 'onedir'}) ...\n")
    result = subprocess.run(pyinstaller_args(onefile), cwd=BASE)
    if result.returncode != 0:
        sys.exit(f"PyInstaller failed ({result.returncode})")


def find_inno() -> str | None:
    for path in INNO_CANDIDATES:
        if os.path.exists(path):
            return path
    return shutil.which("ISCC.exe")


def run_inno() -> None:
    iscc = find_inno()
    if not iscc:
        print("\nInno Setup not found. Install it from "
              "https://jrsoftware.org/isdl.php then re-run with --installer,")
        print("or compile installer.iss in the Inno Setup IDE.")
        return
    script = os.path.join(BASE, "installer.iss")
    print(f"\ninno setup -> {script}\n")
    result = subprocess.run([iscc, script], cwd=BASE)
    if result.returncode != 0:
        sys.exit(f"Inno Setup failed ({result.returncode})")
    print(f"\nInstaller written to {os.path.join(DIST, 'installer')}")


def main() -> None:
    onefile = "--onefile" in sys.argv
    installer = "--installer" in sys.argv
    if onefile and installer:
        sys.exit("--onefile and --installer are mutually exclusive "
                 "(the installer ships the folder build)")

    preflight()
    run_pyinstaller(onefile)

    if onefile:
        print(f"\nPortable exe: {os.path.join(DIST, APP_NAME + '.exe')}")
    else:
        print(f"\nFolder build: {os.path.join(DIST, APP_NAME)}")
    if installer:
        run_inno()


if __name__ == "__main__":
    main()
