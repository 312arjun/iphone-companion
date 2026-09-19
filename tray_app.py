"""
tray_app.py - run the iPhone notification bridge in the background, with a
system tray icon.

  pythonw tray_app.py        (no console window)
  python  tray_app.py        (console visible, handy for debugging)
  run_hidden.vbs             (double-click / Startup shortcut)

Tray menu: live status, pause banners, test banner, force reconnect, open log,
quit. The icon turns green when ANCS is subscribed, amber while reconnecting,
grey when paused.

Requires: pystray (pip install pystray). Everything else is already here.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))

import paths                                     # noqa: E402  (stdlib only)

LOG_PATH = paths.LOG_PATH
MAX_LOG_BYTES = 2 * 1024 * 1024


def _init_logging() -> None:
    """
    Under pythonw there is no stdout, so every print() in the project would
    blow up. Point stdout/stderr at a rotating-ish log file before anything
    else imports.
    """
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_LOG_BYTES:
            os.replace(LOG_PATH, LOG_PATH + ".1")
    except OSError:
        pass
    handle = open(LOG_PATH, "a", buffering=1, encoding="utf-8", errors="replace")
    if sys.stdout is None or not sys.stdout.isatty():
        sys.stdout = handle
        sys.stderr = handle
    print(f"\n===== tray_app started {time.strftime('%Y-%m-%d %H:%M:%S')} =====")


_init_logging()
os.chdir(paths.DATA_DIR)
if not paths.FROZEN:
    sys.path.insert(0, BASE)

from PIL import Image, ImageDraw                    # noqa: E402
import pystray                                      # noqa: E402
from pystray import Menu, MenuItem                  # noqa: E402

import app_ble                                      # noqa: E402
import appicon                                      # noqa: E402
import notify                                       # noqa: E402
from status import STATUS                           # noqa: E402


# --------------------------------------------------------------------------- #
# tray icon artwork
# --------------------------------------------------------------------------- #

ICON_PX = 64


def _state_key() -> str:
    if STATUS.paused:
        return "paused"
    return "listening" if STATUS.connected else "reconnecting"


def _make_icon(state: str) -> Image.Image:
    return appicon.make(state, ICON_PX)


# --------------------------------------------------------------------------- #
# BLE worker
# --------------------------------------------------------------------------- #

def _ble_thread() -> None:
    while True:
        try:
            # max_fails=0 -> never give up; the tray is a long-running service
            asyncio.run(app_ble.run(max_fails=0))
        except Exception as exc:
            print(f"[tray] BLE loop crashed: {exc}")
            STATUS.set_state(f"Crashed: {exc}", connected=False)
        print("[tray] BLE loop exited, restarting in 10s")
        time.sleep(10)


# --------------------------------------------------------------------------- #
# menu actions
# --------------------------------------------------------------------------- #

def _on_pause(icon, item) -> None:
    STATUS.paused = not STATUS.paused
    print(f"[tray] banners {'paused' if STATUS.paused else 'resumed'}")
    icon.icon = _make_icon(_state_key())
    icon.title = STATUS.tooltip()


def _on_test(icon, item) -> None:
    notify.show_notification("WhatsApp", "Tray test",
                             "If you can read this, the bridge is alive.",
                             "net.whatsapp.WhatsApp")


def _on_reconnect(icon, item) -> None:
    if app_ble.drop_link():
        print("[tray] forced a reconnect")
        STATUS.set_state("Reconnecting (manual)", connected=False)
    else:
        print("[tray] no live link to drop")


def _on_log(icon, item) -> None:
    try:
        os.startfile(LOG_PATH)                       # noqa: S606
    except Exception:
        subprocess.Popen(["notepad.exe", LOG_PATH])


def _on_folder(icon, item) -> None:
    try:
        os.startfile(paths.DATA_DIR)                 # noqa: S606
    except Exception:
        pass


def _on_quit(icon, item) -> None:
    print("[tray] quit requested")
    try:
        if app_ble.LOOP:
            app_ble.LOOP.call_soon_threadsafe(app_ble.LOOP.stop)
    except Exception:
        pass
    icon.stop()


def _build_menu() -> Menu:
    return Menu(
        MenuItem(lambda item: STATUS.state, None, enabled=False),
        MenuItem(lambda item: STATUS.battery_text(), None, enabled=False),
        MenuItem(lambda item: STATUS.summary(), None, enabled=False),
        Menu.SEPARATOR,
        MenuItem("Pause banners", _on_pause,
                 checked=lambda item: STATUS.paused),
        MenuItem("Test banner", _on_test),
        MenuItem("Reconnect now", _on_reconnect),
        Menu.SEPARATOR,
        MenuItem("Open log", _on_log),
        MenuItem("Open data folder", _on_folder),
        MenuItem("Quit", _on_quit),
    )


# --------------------------------------------------------------------------- #
# icon refresh
# --------------------------------------------------------------------------- #

def _watch(icon) -> None:
    last = None
    while True:
        key = _state_key()
        if key != last:
            icon.icon = _make_icon(key)
            last = key
        icon.title = STATUS.tooltip()
        time.sleep(2)


def main() -> None:
    threading.Thread(target=_ble_thread, name="ble", daemon=True).start()

    icon = pystray.Icon(
        "ancs_notifier",
        icon=_make_icon("reconnecting"),
        title="iPhone Notifications\nStarting\u2026",
        menu=_build_menu(),
    )
    threading.Thread(target=_watch, args=(icon,), name="tray-watch",
                     daemon=True).start()
    icon.run()                                       # blocks on the main thread


if __name__ == "__main__":
    main()
