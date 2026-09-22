"""
qt_main.py - the application. Run this instead of tray_app.py.

    pythonw qt_main.py          # no console
    python  qt_main.py          # console, for debugging

Threading: Qt owns the main thread, the BLE asyncio loop runs on a daemon
thread. Nothing crosses that boundary directly - the BLE side calls
notify.set_sink()'s callback, which emits a Qt signal, and Qt delivers it on
the GUI thread. Media commands go the other way through
asyncio.run_coroutine_threadsafe.

While the dashboard is visible, notifications route into the window. When it
is hidden they appear as desktop banners.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import paths                                            # noqa: E402
import applog                                           # noqa: E402


def _init_logging() -> None:
    """pythonw has no stdout, so every print() would raise on None."""
    try:
        if (os.path.exists(paths.LOG_PATH)
                and os.path.getsize(paths.LOG_PATH) > 2 * 1024 * 1024):
            os.replace(paths.LOG_PATH, paths.LOG_PATH + ".1")
    except OSError:
        pass
    if sys.stdout is None or not getattr(sys.stdout, "isatty", lambda: False)():
        handle = open(paths.LOG_PATH, "a", buffering=1, encoding="utf-8",
                      errors="replace")
        sys.stdout = handle
        sys.stderr = handle


_init_logging()

from PySide6.QtCore import QObject, Qt, QTimer, Signal                # noqa: E402
from PySide6.QtGui import (QAction, QIcon, QKeySequence, QPixmap,
                           QShortcut)                          # noqa: E402
from PySide6.QtWidgets import (QApplication, QMenu, QSystemTrayIcon)  # noqa: E402

import ams                                              # noqa: E402
import app_ble                                          # noqa: E402
import appicon                                          # noqa: E402
import notify                                           # noqa: E402
import prefs                                            # noqa: E402
import simulate                                         # noqa: E402
import singleton                                        # noqa: E402
import spotify                                          # noqa: E402
import theme                                            # noqa: E402
from dashboard import Dashboard                         # noqa: E402
from qt_toast import MANAGER                            # noqa: E402
from store import DEVICE, FEED, MEDIA                   # noqa: E402


def _tray_pixmap(state: str, plain: bool = False) -> QIcon:
    """Reuse the PIL icon art so the exe, the tray and the window agree."""
    image = (appicon.plain(256) if plain
             else appicon.make(state, 64)).convert("RGBA")
    data = image.tobytes("raw", "RGBA")
    from PySide6.QtGui import QImage
    qimage = QImage(data, image.width, image.height, QImage.Format_RGBA8888)
    return QIcon(QPixmap.fromImage(qimage.copy()))


class Bridge(QObject):
    """Marshals BLE-thread events onto the Qt thread."""

    toast = Signal(dict)
    dismiss = Signal(object)
    scanned = Signal(list)

    def __init__(self):
        super().__init__()
        self.toast.connect(self._on_toast)
        self.dismiss.connect(self._on_dismiss)
        self.dashboard: Dashboard | None = None

    def _on_toast(self, item: dict) -> None:
        if self.dashboard is not None and self.dashboard.isVisible():
            self.dashboard.push_toast(item)
        else:
            MANAGER.show(item)

    def _on_dismiss(self, key) -> None:
        MANAGER.dismiss_key(key)


class Application:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("iPhone Companion")
        theme.resolve_fonts()          # must precede the stylesheet
        theme.apply_mode(prefs.get("theme_mode"))   # and so must the palette
        self.app.setStyleSheet(theme.sheet())

        window_icon = _tray_pixmap("listening", plain=True)
        self.app.setWindowIcon(window_icon)

        # Before the Dashboard is built, so the Notifications page and the
        # Recent Notifications card render with history already in place
        # rather than appearing empty and then filling in.
        restored = FEED.load()
        if restored:
            applog.log("restored %d notification(s) from history" % restored,
                       "store")

        self.bridge = Bridge()
        self.dashboard = Dashboard()
        self.bridge.dashboard = self.dashboard
        self.dashboard.media_command.connect(self.send_media)
        self.dashboard.volume_set.connect(self.set_volume)
        self.dashboard.scan_requested.connect(self.scan_devices)
        self.dashboard.device_selected.connect(self.use_device)
        self.bridge.scanned.connect(self.dashboard.show_scan_results)
        spotify.CLIENT.start()

        notify.set_sink(self.bridge.toast.emit, self.bridge.dismiss.emit)

        self.tray = QSystemTrayIcon(_tray_pixmap("reconnecting"))
        self.tray.setToolTip("iPhone Connect\nStarting")
        self.tray.activated.connect(self._tray_click)
        self.tray.setContextMenu(self._menu())
        self.tray.show()

        self._state = "reconnecting"
        self.watch = QTimer()
        self.watch.timeout.connect(self._update_tray)
        self.watch.start(2000)

        # Ctrl+Q from the window, and Ctrl+C from the console, both quit.
        self.quit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self.dashboard)
        self.quit_shortcut.activated.connect(self.quit)
        self._install_signals()

        threading.Thread(target=self._ble_thread, name="ble",
                         daemon=True).start()

    # ------------------------------------------------------------------ #

    def _menu(self) -> QMenu:
        """
        The menu and its actions must be kept referenced. The first version
        built them as locals, so CPython freed the QMenu the moment this
        method returned and right-clicking the tray showed nothing at all -
        including Quit.
        """
        menu = QMenu()
        self.menu = menu

        self.action_open = menu.addAction("Open iPhone Connect")
        self.action_open.triggered.connect(self.show_dashboard)
        menu.addSeparator()

        self.action_pause = menu.addAction("Pause banners")
        self.action_pause.setCheckable(True)
        self.action_pause.toggled.connect(self._on_pause)

        # QAction.triggered passes checked=False, which would land in the
        # first parameter - hence the lambdas rather than direct connections.
        self.simulate_menu = menu.addMenu("Simulate")
        self.action_sim_call = self.simulate_menu.addAction("Incoming call")
        self.action_sim_call.triggered.connect(self._on_sim_call)
        self.action_sim_missed = self.simulate_menu.addAction("Missed call")
        self.action_sim_missed.triggered.connect(
            lambda: self._simulate(simulate.missed_call))
        self.action_sim_message = self.simulate_menu.addAction("Message")
        self.action_sim_message.triggered.connect(
            lambda: self._simulate(simulate.message))
        self.action_sim_otp = self.simulate_menu.addAction("OTP message")
        self.action_sim_otp.triggered.connect(
            lambda: self._simulate(simulate.otp_message))
        # The negative control. A banner that looks like an OTP but carries a
        # transaction amount must NOT grow a copy pill, and that is far easier
        # to get wrong than the positive case - so it gets its own menu entry
        # rather than being something to remember to test by hand.
        self.action_sim_nootp = self.simulate_menu.addAction(
            "Bank alert (no code)")
        self.action_sim_nootp.triggered.connect(
            lambda: self._simulate(simulate.bank_alert))
        self.simulate_menu.addSeparator()
        self.action_sim_all = self.simulate_menu.addAction("All toasts")
        self.action_sim_all.triggered.connect(
            lambda: self._simulate(simulate.all_toasts))

        self.action_reconnect = menu.addAction("Reconnect now")
        self.action_reconnect.triggered.connect(lambda: app_ble.drop_link())
        menu.addSeparator()

        self.action_log = menu.addAction("Open log")
        self.action_log.triggered.connect(self._on_log)

        self.action_quit = menu.addAction("Quit")
        self.action_quit.triggered.connect(self.quit)
        return menu

    def _on_log(self) -> None:
        try:
            os.startfile(paths.LOG_PATH)                       # noqa: S606
        except Exception as exc:
            applog.log(f"could not open log: {exc}", "ui")

    def _install_signals(self) -> None:
        """
        Qt's event loop never returns to the interpreter, so Python signal
        handlers only fire while some other Python code happens to be running.
        A short idle timer gives the interpreter a slot to run them in, which
        makes Ctrl+C work as expected.
        """
        for number in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(number, lambda *_args: self.quit())
            except Exception:
                pass
        self.signal_timer = QTimer()
        self.signal_timer.timeout.connect(lambda: None)
        self.signal_timer.start(200)

    def _tray_click(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_dashboard()

    def show_dashboard(self) -> None:
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()
        MANAGER.clear()                  # desktop banners hand over to the window

    def _on_pause(self, checked: bool) -> None:
        from status import STATUS
        STATUS.paused = checked
        applog.log(f"banners {'paused' if checked else 'resumed'}", "ui")

    def _on_test(self) -> None:
        simulate.message()

    def _simulate(self, action) -> None:
        """
        Desktop toasts only show when the dashboard is hidden, so hide it
        first - otherwise this quietly adds a row to the in-window list and
        looks like nothing happened.
        """
        if self.dashboard.isVisible():
            self.dashboard.hide()
        try:
            action()
        except Exception as exc:
            applog.log(f"simulation failed: {exc}", "sim")

    def _on_sim_call(self) -> None:
        self._simulate(simulate.incoming_call)

    def _update_tray(self) -> None:
        device = DEVICE.snapshot()
        from status import STATUS
        state = ("paused" if STATUS.paused
                 else "listening" if device["connected"] else "reconnecting")
        if state != self._state:
            self.tray.setIcon(_tray_pixmap(state))
            self._state = state
        battery = (f" \u00b7 {device['battery']}%"
                   if device["battery"] is not None else "")
        self.tray.setToolTip(
            f"iPhone Connect\n"
            f"{'Connected' if device['connected'] else device['state']}{battery}")

    # ------------------------------------------------------------------ #

    def send_media(self, command: int) -> None:
        """Dashboard button -> AMS write, marshalled onto the BLE loop."""
        loop, client = app_ble.LOOP, app_ble.CLIENT
        if loop is None or client is None:
            applog.log("media command ignored: not connected", "ui")
            return
        asyncio.run_coroutine_threadsafe(ams.send(client, command), loop)

    def set_volume(self, percent: int) -> None:
        """
        Absolute volume from the slider.

        Spotify can set it outright. AMS cannot - it only has step up / step
        down - so the target becomes a run of steps, sent as ONE sequential
        coroutine. Firing them as separate concurrent writes is what made the
        slider appear dead: the phone dropped all but the first.
        """
        if spotify.CLIENT.connected:
            threading.Thread(target=spotify.CLIENT.set_volume,
                             args=(percent,), daemon=True).start()
            return

        loop, client = app_ble.LOOP, app_ble.CLIENT
        if loop is None or client is None:
            applog.log("volume ignored: not connected", "ui")
            return

        current = MEDIA.snapshot()["volume"]
        if current is None:
            applog.log("volume ignored: the phone has not reported a level "
                       "yet - play something first", "ui")
            return
        steps = int(round((percent / 100 - current) * 16))
        if not steps:
            return
        applog.log(f"volume {int(current * 100)}% -> {percent}% "
                   f"({steps:+d} steps)", "ui", debug=True)
        asyncio.run_coroutine_threadsafe(ams.step_volume(client, steps), loop)

    def scan_devices(self) -> None:
        """
        Run a scan on the BLE loop and hand the result back through a signal.

        If the loop is not up yet there is nothing to schedule on, so answer
        with an empty list rather than leaving the button spinning forever.
        """
        loop = app_ble.LOOP
        if loop is None:
            applog.log("scan ignored: BLE loop not running", "ui")
            self.bridge.scanned.emit([])
            return

        future = asyncio.run_coroutine_threadsafe(app_ble.scan_all(), loop)

        def deliver(done) -> None:
            try:
                self.bridge.scanned.emit(done.result() or [])
            except Exception as exc:
                applog.log(f"scan failed: {exc}", "ui")
                self.bridge.scanned.emit([])

        future.add_done_callback(deliver)

    def use_device(self, address: str) -> None:
        """Remember a new phone and bounce the link so it reconnects to it."""
        app_ble.save_address(address)
        applog.log(f"device set to {address}", "ui")
        if not app_ble.drop_link():
            applog.log("no live link to drop - it will be used on the next "
                       "connect", "ui")

    def _ble_thread(self) -> None:
        while True:
            try:
                asyncio.run(app_ble.run(max_fails=0))
            except Exception as exc:
                applog.log(f"loop crashed: {exc}", "ble")
            time.sleep(10)

    def quit(self) -> None:
        applog.log("quitting", "app")
        try:
            if app_ble.LOOP:
                app_ble.LOOP.call_soon_threadsafe(app_ble.LOOP.stop)
        except Exception:
            pass
        try:
            MANAGER.clear()
            self.dashboard.hide()
            self.tray.hide()
        except Exception:
            pass
        self.app.quit()

    def run(self) -> int:
        applog.log("iPhone Connect started", "app")
        return self.app.exec()


if __name__ == "__main__":
    # Checked before anything else runs. A second instance must not reach
    # the BLE thread, the feed database or prefs.json - it would fight the
    # first for the phone's link and overwrite its settings. Raising the
    # existing window makes a double-clicked shortcut do the useful thing
    # instead of appearing to do nothing.
    if not singleton.acquire():
        applog.log(singleton.already_running_message(), "app")
        if not singleton.raise_existing():
            applog.log("the running copy has no window open; it is in the "
                       "tray", "app")
        sys.exit(0)
    sys.exit(Application().run())
