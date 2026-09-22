"""
Notification display layer.

The BLE thread calls show_notification(). Where it ends up depends on what
registered itself:

  1. a sink (qt_main registers one) - the Qt app decides between an in-window
     card and a desktop banner
  2. macos_toast - the standalone Tk banner, for running app_ble.py bare
  3. windows-toasts - native toast fallback
  4. console only

Every notification is recorded in store.FEED unless an explicit keyword rule
asks for it to be dropped, so the dashboard's history stays complete even
for ones that never raised a banner. See rules.py for the policy.
"""

from __future__ import annotations

import time

import applog
import rules
from status import STATUS
from store import FEED, Item

_sink = None
_sink_dismiss = None

_MODE = None
_REASON = ""
_mac_toast = None
_mac_dismiss = None
_toaster = None


def _ensure_fallback() -> None:
    """
    Resolve a display fallback, once, on first use.

    This is deliberately lazy. macos_toast sets the process DPI awareness at
    import time, and process DPI awareness can only be set once - importing it
    eagerly inside the Qt app makes Qt's own SetProcessDpiAwarenessContext()
    fail with "Access is denied". When a sink is registered we never need the
    Tk banner at all, so we simply never import it.
    """
    global _MODE, _REASON, _mac_toast, _mac_dismiss, _toaster
    if _MODE is not None:
        return

    try:
        from macos_toast import dismiss_toast, show_toast
        _mac_toast, _mac_dismiss = show_toast, dismiss_toast
        _MODE = "mac"
        return
    except Exception as exc:
        _REASON = f"macos_toast unavailable ({exc})"

    try:
        from windows_toasts import Toast, WindowsToaster
        globals()["Toast"] = Toast
        _toaster = WindowsToaster("iPhone Connect")
        _MODE = "win"
    except Exception as exc:
        _MODE = "console"
        _REASON += f"; windows_toasts unavailable ({exc})"

    if _REASON:
        applog.log(f"display fallback '{_MODE}': {_REASON}", "note")


def set_sink(sink, dismiss=None) -> None:
    """Hand display over to the Qt app. Called once, at startup."""
    global _sink, _sink_dismiss
    _sink = sink
    _sink_dismiss = dismiss


def show_notification(app_name: str, title: str, body: str,
                      bundle_id: str | None = None, actions=None,
                      hold_ms: int | None = None, key=None,
                      style: str | None = None, category: str = ""):
    """
    Show one incoming notification.

    actions: list of (label, callback, kind).
    style:   "call" for the call layout, None for the standard one.
    key:     the ANCS uid, so it can be dismissed when the phone clears it.
    """
    headline = title or app_name

    # One choke point for policy: everything reaching a display passes here,
    # so the rules only have to be applied in one place. See rules.py.
    verdict = rules.decide(app=app_name, title=headline, body=body or "",
                           bundle_id=bundle_id or "", style=style)
    if verdict == rules.DROP:
        applog.log(f"dropped by rule: {app_name}: {headline}", "note")
        return

    FEED.add(Item(at=time.time(), app=app_name, bundle_id=bundle_id or "",
                  title=headline, body=body or "", category=category,
                  uid=key, style=style, verdict=verdict))
    STATUS.note(app_name, headline)

    # Bodies arrive with embedded newlines - a promotional push is often
    # three lines - so they are flattened and clipped for the log. The full
    # text is in the feed; the log is for scanning, not archiving.
    flat = " ".join((body or "").split())
    label = f"{app_name}: {headline}"
    if flat:
        label += f" - {flat[:90]}" + ("\u2026" if len(flat) > 90 else "")
    applog.log(label, "note")

    if STATUS.paused:
        return

    # Recorded above, so it is in the feed when the user looks - it just
    # never raises a banner. Only the headline is repeated here: the line
    # above already carries the body, and printing it twice turns one
    # silenced promo into six lines of log.
    if verdict == rules.SILENT:
        applog.log(f"silenced by rule: {app_name}: {headline}", "note")
        return

    item = {
        "app": app_name, "title": headline, "body": body or "",
        "bundle_id": bundle_id, "actions": actions or [],
        "hold_ms": hold_ms, "key": key, "style": style,
        "category": category,      # the toast picks its variant from this
        "at": time.time(),         # toasts show the age, as the phone does
    }

    if _sink is not None:
        try:
            _sink(item)
            return
        except Exception as exc:
            applog.log(f"sink failed: {exc}", "note")

    _ensure_fallback()

    if _MODE == "mac":
        try:
            _mac_toast(app_name, headline, body or "", bundle_id,
                       actions=actions, hold_ms=hold_ms, key=key, style=style)
        except Exception as exc:
            applog.log(f"banner failed: {exc}", "note")
        return

    if _MODE == "win":
        try:
            toast = Toast()
            toast.text_fields = [label]
            _toaster.show_toast(toast)
        except Exception as exc:
            applog.log(f"toast failed: {exc}", "note")


def dismiss_notification(key):
    """The notification went away on the phone - pull whatever is showing."""
    if key is None:
        return
    if _sink_dismiss is not None:
        try:
            _sink_dismiss(key)
            return
        except Exception:
            pass
    if _MODE == "mac" and _mac_dismiss is not None:
        try:
            _mac_dismiss(key)
        except Exception:
            pass
