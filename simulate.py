"""
simulate.py - fake phone events, for testing the UI without a real call.

Events are built as real 8-byte Notification Source packets and pushed through
ancs.parse_notification_source() and calls.TRACKER, so the simulation goes
down exactly the same path a genuine notification does: the same parsing, the
same call-state machine, the same duration arithmetic, the same banners.

That matters - a simulation that shortcuts straight to show_notification()
would not exercise the ringing to active transition, and the live duration
counter would never start.

Fake uids start high so they cannot collide with the phone's own.
"""

from __future__ import annotations

import struct

import ancs
import calls
from applog import log
from notify import dismiss_notification, show_notification

CAT_INCOMING = 1
CAT_MISSED = 2
CAT_ACTIVE = 12

_next_uid = 900_000


def _uid() -> int:
    global _next_uid
    _next_uid += 1
    return _next_uid


def _packet(event_id: int, flags: int, category: int, uid: int) -> bytes:
    """EventID | EventFlags | CategoryID | CategoryCount | UID(uint32 LE)"""
    return bytes([event_id, flags, category, 1]) + struct.pack("<I", uid)


def _feed(event_id: int, flags: int, category: int, uid: int):
    """Push one synthetic event through the real parser and tracker."""
    info = ancs.parse_notification_source(
        _packet(event_id, flags, category, uid))
    finished = calls.TRACKER.on_notification(info)
    if finished is not None:
        _report(finished)
    return info


def _report(call) -> None:
    import app_ble                    # late, to avoid an import cycle
    app_ble._report_call(call)


# --------------------------------------------------------------------------- #
# public
# --------------------------------------------------------------------------- #

def incoming_call(name: str = "Alex Whitfield",
                  app: str = "Phone",
                  bundle_id: str = "com.apple.mobilephone") -> None:
    """A ringing call, with Answer and Decline that actually do something."""
    ring_flags = (ancs.FLAG_IMPORTANT | ancs.FLAG_POSITIVE_ACTION
                  | ancs.FLAG_NEGATIVE_ACTION)
    ring_uid = _uid()
    _feed(ancs.EVENT_ADDED, ring_flags, CAT_INCOMING, ring_uid)
    calls.TRACKER.on_details(ring_uid, app, bundle_id, name, "mobile")
    log(f"simulating an incoming call from {name}", "sim")

    def answer() -> None:
        dismiss_notification(ring_uid)
        _feed(ancs.EVENT_REMOVED, ring_flags, CAT_INCOMING, ring_uid)

        active_uid = _uid()
        active_flags = ancs.FLAG_IMPORTANT | ancs.FLAG_NEGATIVE_ACTION
        _feed(ancs.EVENT_ADDED, active_flags, CAT_ACTIVE, active_uid)
        calls.TRACKER.on_details(active_uid, app, bundle_id, name, "mobile")
        log("simulated call answered", "sim")

        def hang_up() -> None:
            dismiss_notification(active_uid)
            _feed(ancs.EVENT_REMOVED, active_flags, CAT_ACTIVE, active_uid)
            log("simulated call ended", "sim")

        show_notification(app, name, "", bundle_id,
                          actions=[("End Call", hang_up, "negative")],
                          style="active_call", key=active_uid,
                          category="Active Call")

    def decline() -> None:
        dismiss_notification(ring_uid)
        _feed(ancs.EVENT_REMOVED, ring_flags, CAT_INCOMING, ring_uid)
        _feed(ancs.EVENT_ADDED, ancs.FLAG_NEGATIVE_ACTION, CAT_MISSED, _uid())
        log("simulated call declined", "sim")

    show_notification(app, name, "", bundle_id,
                      actions=[("Answer", answer, "positive"),
                               ("Decline", decline, "negative")],
                      style="call", key=ring_uid,
                      category="Incoming Call")


def message(name: str = "Priya Sharma",
            body: str = "Something else happened I don't know exactly the "
                        "steering was wobbly, some good bike mechanic is "
                        "needed to fix that",
            app: str = "WhatsApp",
            bundle_id: str = "net.whatsapp.WhatsApp") -> None:
    """A two-line message banner with a Clear action."""
    uid = _uid()
    log(f"simulating a {app} message", "sim")
    show_notification(app, name, body, bundle_id,
                      actions=[("Clear", lambda: None, "negative")],
                      key=uid, category="Social")


def otp_message(body: str = "LOGIN to your Flipkart account using OTP 152634. "
                            "DO NOT SHARE this OTP with anyone.",
                name: str = "FLPKRT-S",
                app: str = "Messages",
                bundle_id: str = "com.apple.MobileSMS") -> None:
    """
    An SMS carrying a one-time code, which should raise a banner with the
    code on a pill instead of the usual action button.

    Uses a real-world body on purpose: it is long enough that the digits fall
    off the end of the elided line, which is the case the pill exists for.
    Pass a body with no code in it to check that the pill stays away.
    """
    uid = _uid()
    log(f"simulating an OTP message from {name}", "sim")
    show_notification(app, name, body, bundle_id, key=uid, category="Other")


def bank_alert(body: str = "Rs.4999.00 debited from a/c XX1234 on 18-09-26 "
                           "to VPA merchant@upi. Ref 402817732190.",
               name: str = "HDFCBK",
               app: str = "Messages",
               bundle_id: str = "com.apple.MobileSMS") -> None:
    """
    The negative control: an SMS stuffed with digits and none of them a code.

    This banner must come up with NO copy pill. It is the case worth firing
    deliberately, because a false positive here would put an account number
    on the clipboard, which is a far worse failure than never showing the
    pill at all.
    """
    uid = _uid()
    log(f"simulating a bank alert from {name} (expect no copy pill)", "sim")
    show_notification(app, name, body, bundle_id, key=uid, category="Other")


def missed_call(name: str = "Mum",
                app: str = "Phone",
                bundle_id: str = "com.apple.mobilephone") -> None:
    """
    A call that rang and was never answered.

    The events alone only update the Calls history - a real missed call gets
    its banner from the Data Source reply, which a simulation has no way to
    produce, so the banner is raised explicitly here. iOS labels the actions
    "Dial" and "Clear" for this category, and it uses the standard layout
    rather than the call layout, which is why there is no avatar.
    """
    ring_flags = (ancs.FLAG_IMPORTANT | ancs.FLAG_POSITIVE_ACTION
                  | ancs.FLAG_NEGATIVE_ACTION)
    ring_uid = _uid()
    _feed(ancs.EVENT_ADDED, ring_flags, CAT_INCOMING, ring_uid)
    calls.TRACKER.on_details(ring_uid, app, bundle_id, name, "mobile")
    _feed(ancs.EVENT_REMOVED, ring_flags, CAT_INCOMING, ring_uid)

    missed_uid = _uid()
    _feed(ancs.EVENT_ADDED, ring_flags, CAT_MISSED, missed_uid)
    log(f"simulated a missed call from {name}", "sim")

    def dial() -> None:
        log("a real missed-call banner would dial back here", "sim")

    show_notification(app, "Missed Call", f"from {name}", bundle_id,
                      actions=[("Dial", dial, "positive"),
                               ("Clear", lambda: None, "negative")],
                      key=missed_uid, category="Missed Call")


def all_toasts() -> None:
    """
    One of each, staggered, so the whole stack can be compared side by side.

    The delays are deliberate: firing them in the same tick would let the
    stack manager position every toast before any had laid itself out, and
    they would overlap.
    """
    from PySide6.QtCore import QTimer

    log("simulating every toast", "sim")
    message()
    QTimer.singleShot(400, missed_call)
    QTimer.singleShot(800, lambda: incoming_call(name="Mum"))
    QTimer.singleShot(1200, otp_message)
    QTimer.singleShot(1600, lambda: message(
        name="Big Fashion Days is Live!",
        body="Get up to 80% off on top brands. Shop now!",
        app="Myntra", bundle_id="com.myntra.Myntra"))
