"""
store.py - everything the GUI displays, in one place.

The BLE thread writes, the Qt thread reads. Both go through a lock, and
readers get plain snapshots (dicts / lists of dataclasses) so the UI never
holds a reference to live mutable state.

Three stores:
  DEVICE  - name, model, manufacturer, battery, connection state
  MEDIA   - AMS player / track / volume
  FEED    - recent notifications, for the Notifications page and the
            in-window toast list
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

MAX_FEED = 120


# --------------------------------------------------------------------------- #
# device
# --------------------------------------------------------------------------- #

class _Device:
    def __init__(self):
        self._lock = threading.Lock()
        self.name = ""
        self.model = ""
        self.manufacturer = ""
        self.ios_version = ""
        self.address = ""
        self.battery: int | None = None
        self.connected = False
        self.state = "Starting"
        self.last_seen: float | None = None

    def update(self, **fields) -> None:
        with self._lock:
            for key, value in fields.items():
                if value is not None and hasattr(self, key):
                    setattr(self, key, value)
            if fields.get("connected"):
                self.last_seen = time.time()

    def touch(self) -> None:
        with self._lock:
            self.last_seen = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "name": self.name or "iPhone",
                "model": self.model,
                "manufacturer": self.manufacturer,
                "ios_version": self.ios_version,
                "address": self.address,
                "battery": self.battery,
                "connected": self.connected,
                "state": self.state,
                "last_seen": self.last_seen,
            }


# --------------------------------------------------------------------------- #
# media (AMS)
# --------------------------------------------------------------------------- #

class _Media:
    def __init__(self):
        self._lock = threading.Lock()
        self.player = ""
        self.title = ""
        self.artist = ""
        self.album = ""
        self.duration = 0.0
        self.elapsed = 0.0
        self.rate = 0.0
        self.playing = False
        self.volume: float | None = None
        self.shuffle = ""
        self.repeat = ""
        self.art_path = ""          # local album art, when Spotify is linked
        self.source = "ams"         # ams | spotify
        self._elapsed_at = time.monotonic()

    def set_playback(self, state: int, rate: float, elapsed: float) -> None:
        with self._lock:
            self.playing = state == 1
            self.rate = rate
            self.elapsed = elapsed
            self._elapsed_at = time.monotonic()

    def update(self, **fields) -> None:
        with self._lock:
            for key, value in fields.items():
                if value is not None and hasattr(self, key):
                    setattr(self, key, value)

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = self.elapsed
            if self.playing and self.rate:
                # AMS only pushes elapsed on change, so extrapolate between
                # updates or the progress bar sits still while music plays.
                elapsed += (time.monotonic() - self._elapsed_at) * self.rate
            if self.duration:
                elapsed = min(elapsed, self.duration)
            return {
                "player": self.player,
                "title": self.title,
                "artist": self.artist,
                "album": self.album,
                "duration": self.duration,
                "elapsed": max(0.0, elapsed),
                "playing": self.playing,
                "volume": self.volume,
                "shuffle": self.shuffle,
                "repeat": self.repeat,
                "art_path": self.art_path,
                "source": self.source,
                "has_track": bool(self.title or self.artist),
            }


# --------------------------------------------------------------------------- #
# notification feed
# --------------------------------------------------------------------------- #

@dataclass
class Item:
    at: float
    app: str
    bundle_id: str
    title: str
    body: str
    category: str = ""
    uid: int | None = None
    actions: list = field(default_factory=list)
    style: str | None = None


class _Feed:
    def __init__(self):
        self._lock = threading.Lock()
        self.items: deque[Item] = deque(maxlen=MAX_FEED)
        self.total = 0

    def add(self, item: Item) -> None:
        with self._lock:
            self.items.appendleft(item)
            self.total += 1

    def recent(self, limit: int = 20) -> list[Item]:
        with self._lock:
            return list(self.items)[:limit]

    def count(self) -> int:
        with self._lock:
            return self.total

    def clear(self) -> None:
        with self._lock:
            self.items.clear()


DEVICE = _Device()
MEDIA = _Media()
FEED = _Feed()


def ago(when: float | None) -> str:
    """'2m ago' style relative time, as in the dashboard mock."""
    if not when:
        return "\u2014"
    delta = max(0, int(time.time() - when))
    if delta < 10:
        return "Just now"
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"
