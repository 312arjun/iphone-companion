"""
status.py - shared runtime state, so the tray UI, the BLE loop and the
display layer can see each other without importing each other.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class _Status:
    def __init__(self):
        self._lock = threading.Lock()
        self.connected = False
        self.address: str | None = None
        self.paused = False
        self.count = 0
        self.battery: int | None = None
        self.state = "Starting\u2026"
        self.last: tuple[float, str, str] | None = None
        self.last_call: str | None = None
        self.log = deque(maxlen=200)

    # -- writers --------------------------------------------------------- #

    def set_state(self, text: str, connected: bool | None = None) -> None:
        with self._lock:
            self.state = text
            if connected is not None:
                self.connected = connected
            self.log.append((time.time(), text))

    def note(self, app: str, title: str) -> None:
        with self._lock:
            self.count += 1
            self.last = (time.time(), app, title)

    def set_call_summary(self, text: str) -> None:
        with self._lock:
            self.last_call = text

    # -- readers --------------------------------------------------------- #

    def tooltip(self) -> str:
        with self._lock:
            head = "iPhone Notifications"
            line = self.state if not self.connected else f"Listening \u00b7 {self.count} today"
            if self.paused:
                line = "Paused \u00b7 " + line
            if self.battery is not None:
                line += f" \u00b7 {self.battery}% battery"
            return f"{head}\n{line}"

    def battery_text(self) -> str:
        with self._lock:
            if self.battery is None:
                return "Battery: unknown"
            return f"iPhone battery: {self.battery}%"

    def summary(self) -> str:
        with self._lock:
            if not self.last:
                return self.state
            when, app, title = self.last
            return f"{time.strftime('%H:%M', time.localtime(when))}  {app}: {title}"[:60]


STATUS = _Status()
