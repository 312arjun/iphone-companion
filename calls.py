"""
calls.py - reconstruct call state from ANCS notification events.

ANCS has no call object and no duration field. What it does give us, proven
from probe logs, is a tight event sequence:

    Incoming Call ADDED                    ringing starts
    Incoming Call REMOVED  +  Active Call ADDED   (same millisecond) -> answered
    Incoming Call REMOVED  then Missed Call ADDED                    -> missed
    Active Call REMOVED                    call over

So duration is (Active Call REMOVED - Active Call ADDED), measured locally.
Observed accuracy against a stopwatch was well under a second, which is fine
for display.

An Active Call with no preceding Incoming Call is an outgoing call dialled on
the phone - the same events arrive, just without the ringing stage.

Everything here is plain state, no I/O, so the UI can poll it freely.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

import ancs

CAT_INCOMING = 1
CAT_MISSED = 2
CAT_ACTIVE = 12

# How close the Active Call must follow the Incoming removal to count as
# "answered". Probes showed the two land in the same millisecond; 2s is slack.
ANSWER_WINDOW = 2.0
RINGING_TIMEOUT = 180.0          # abandon a ringing call we never resolved
HISTORY = 40


def format_duration(seconds: float) -> str:
    total = int(round(max(0.0, seconds)))
    if total >= 3600:
        return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    return f"{total // 60}:{total % 60:02d}"


@dataclass
class Call:
    uid: int
    app: str = ""
    bundle_id: str = ""
    title: str = ""
    subtitle: str = ""
    direction: str = "incoming"          # incoming | outgoing
    state: str = "ringing"               # ringing | active | ended | missed
    ringing_at: float | None = None
    ring_ended_at: float | None = None
    started_at: float | None = None      # when it became an Active Call
    ended_at: float | None = None
    answered: bool = False

    @property
    def duration(self) -> float:
        """Seconds on the call. Live while active, final once ended."""
        if self.started_at is None:
            return 0.0
        return (self.ended_at or time.time()) - self.started_at

    @property
    def duration_text(self) -> str:
        return format_duration(self.duration)

    def label(self) -> str:
        return self.title or self.app or "Unknown"


class CallTracker:
    """
    Fed from the Notification Source handler. Returns a Call whenever one
    reaches a terminal state, so the caller can show or log it.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.ringing: Call | None = None
        self.active: Call | None = None
        self.history: deque[Call] = deque(maxlen=HISTORY)

    # -- ingest ----------------------------------------------------------- #

    def on_notification(self, info: dict) -> Call | None:
        """
        Handle one parsed Notification Source packet. Returns a finished Call
        (ended or missed) or None.
        """
        category = info.get("category")
        if category not in (CAT_INCOMING, CAT_MISSED, CAT_ACTIVE):
            return None

        event = info.get("event_id")
        uid = info.get("uid")
        now = time.time()

        with self._lock:
            self._expire(now)

            if category == CAT_INCOMING:
                if event == ancs.EVENT_ADDED:
                    self.ringing = Call(uid=uid, ringing_at=now,
                                        direction="incoming", state="ringing")
                elif event == ancs.EVENT_REMOVED and self._is_ringing(uid):
                    # Could mean answered or dropped - the next event decides.
                    self.ringing.ring_ended_at = now
                return None

            if category == CAT_ACTIVE:
                if event == ancs.EVENT_ADDED:
                    self.active = self._promote(uid, now)
                    return None
                if event == ancs.EVENT_REMOVED and self._is_active(uid):
                    call = self.active
                    call.ended_at = now
                    call.state = "ended"
                    self.active = None
                    self.history.appendleft(call)
                    return call
                return None

            # CAT_MISSED: the ringing call was never picked up
            if event == ancs.EVENT_ADDED and self.ringing is not None:
                call = self.ringing
                call.state = "missed"
                call.ended_at = now
                self.ringing = None
                self.history.appendleft(call)
                return call
            return None

    def on_details(self, uid: int, app: str, bundle_id: str,
                   title: str, subtitle: str = "") -> None:
        """
        Attach the text from the Data Source, which arrives after the event.
        Matched by uid against whichever call is in flight.
        """
        with self._lock:
            for call in (self.active, self.ringing):
                if call is not None and call.uid == uid:
                    call.app = app or call.app
                    call.bundle_id = bundle_id or call.bundle_id
                    call.title = title or call.title
                    call.subtitle = subtitle or call.subtitle
                    return
            for call in self.history:
                if call.uid == uid and not call.title:
                    call.title = title
                    call.app = app or call.app
                    call.bundle_id = bundle_id or call.bundle_id
                    return

    # -- read ------------------------------------------------------------- #

    def snapshot(self) -> dict:
        """Cheap, lock-free-enough view for the UI to poll."""
        with self._lock:
            call = self.active or self.ringing
            if call is None:
                return {"state": "idle"}
            return {
                "state": call.state,
                "uid": call.uid,
                "who": call.label(),
                "app": call.app,
                "bundle_id": call.bundle_id,
                "direction": call.direction,
                "duration": call.duration,
                "duration_text": call.duration_text,
            }

    def recent(self, limit: int = 10) -> list[Call]:
        with self._lock:
            return list(self.history)[:limit]

    # -- internals -------------------------------------------------------- #

    def _is_ringing(self, uid) -> bool:
        return self.ringing is not None and self.ringing.uid == uid

    def _is_active(self, uid) -> bool:
        return self.active is not None and self.active.uid == uid

    def _promote(self, uid, now) -> Call:
        """Turn the ringing call into an active one, or invent an outgoing."""
        ringing = self.ringing
        answered = bool(
            ringing is not None
            and (now - (ringing.ring_ended_at or ringing.ringing_at or now))
            <= ANSWER_WINDOW
        )
        if ringing is not None:
            call = ringing
            call.uid = uid                       # Active Call gets a fresh uid
            call.answered = answered
        else:
            call = Call(uid=uid, direction="outgoing", answered=True)
        call.state = "active"
        call.started_at = now
        self.ringing = None
        return call

    def _expire(self, now) -> None:
        if (self.ringing is not None
                and now - (self.ringing.ringing_at or now) > RINGING_TIMEOUT):
            self.ringing = None


TRACKER = CallTracker()
