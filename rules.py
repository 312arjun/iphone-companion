"""
rules.py - decide what happens to an incoming notification.

One pure function, `decide()`, sits between the BLE thread and the display
layer. Everything it needs is passed in, so the whole policy is testable
without Qt, Bluetooth or a clock.

Three verdicts:
    SHOW    raise a banner, record it
    SILENT  record it, no banner - it is in the feed when you look
    DROP    neither

Precedence is deliberate and fixed (highest first):

    1. calls                  - never suppressed, whatever else is set
    2. keyword rules          - the most specific thing a user can express
    3. app filter             - allow-list or block-list
    4. priority apps          - override quiet hours
    5. quiet hours            - silence everything else

Calls sit at the top as a safety rail. A block-list entry or a stray keyword
should never be able to hide a ringing phone, and a user who sets "quiet
hours" means notifications, not their sister calling at 1am.

SILENT is preferred over DROP nearly everywhere: a notification you cannot
find later is worse than one you did not want to see now. Only an explicit
keyword rule asking for `drop` discards anything.
"""

from __future__ import annotations

import time

import prefs

SHOW = "show"
SILENT = "silent"
DROP = "drop"

VERDICTS = (SHOW, SILENT, DROP)


def _minutes(clock: str, fallback: int) -> int:
    """'22:30' -> 1350. Bad input falls back rather than raising."""
    try:
        hour, minute = clock.split(":")
        value = int(hour) * 60 + int(minute)
        return value if 0 <= value < 1440 else fallback
    except (ValueError, AttributeError):
        return fallback


def in_quiet_hours(now: float | None = None,
                   start: str | None = None,
                   end: str | None = None) -> bool:
    """
    Is `now` inside the quiet window?

    Handles the overnight case, which is the normal one: 22:00-07:00 wraps
    past midnight, so the test is "after start OR before end" rather than
    "between". A window where start == end is treated as off, not as 24h,
    because that is nearly always a half-finished setting rather than an
    intent to silence everything forever.
    """
    start_m = _minutes(start if start is not None else prefs.get("quiet_start"),
                       22 * 60)
    end_m = _minutes(end if end is not None else prefs.get("quiet_end"),
                     7 * 60)
    if start_m == end_m:
        return False
    stamp = time.localtime(now if now is not None else time.time())
    current = stamp.tm_hour * 60 + stamp.tm_min
    if start_m < end_m:                       # same-day window, e.g. 09:00-17:00
        return start_m <= current < end_m
    return current >= start_m or current < end_m      # overnight


def _keyword_verdict(haystack: str, rules_list) -> str | None:
    """
    First matching keyword rule wins, so order in the list is priority.

    Plain case-insensitive substring matching, not regex. A user typing
    "sale" into a settings box means the word sale, and characters like
    ( [ . * + ? are far likelier to be part of real notification text than
    an intended pattern. Literal matching also means a rule can never be
    "broken" - there is no syntax to get wrong.
    """
    if not haystack:
        return None
    hay = haystack.lower()
    for rule in rules_list or []:
        if not isinstance(rule, dict):
            continue
        word = (rule.get("pattern") or "").strip().lower()
        action = rule.get("action")
        if not word or action not in VERDICTS:
            continue
        if word in hay:
            return action
    return None


def decide(app: str = "", title: str = "", body: str = "",
           bundle_id: str = "", style: str | None = None,
           now: float | None = None, settings: dict | None = None) -> str:
    """
    What to do with one notification. See the module docstring for order.

    `settings` exists for testing: pass a dict to bypass prefs entirely.
    """
    def pref(key):
        if settings is not None:
            return settings.get(key, prefs.DEFAULTS.get(key))
        return prefs.get(key)

    # 1. calls are never suppressed
    if style == "call":
        return SHOW

    bundle = bundle_id or ""

    # 2. keyword rules - most specific expression of intent
    verdict = _keyword_verdict(" ".join((title or "", body or "", app or "")),
                               pref("keyword_rules"))
    if verdict is not None:
        return verdict

    # 3. app filter
    mode = pref("app_filter_mode")
    if mode == "allowlist":
        allowed = pref("app_allowlist") or []
        # An empty allow-list would silence every notification from every
        # app, which nobody means - it is what a half-finished setting looks
        # like, reached by picking the mode before picking any apps. Treated
        # as "off" until at least one app is chosen.
        if allowed and bundle not in allowed:
            return SILENT
    elif mode == "blocklist":
        if bundle in (pref("app_blocklist") or []):
            return SILENT

    # 4. priority apps ignore quiet hours
    if bundle in (pref("priority_apps") or []):
        return SHOW

    # 5. quiet hours
    if pref("quiet_enabled") and in_quiet_hours(
            now, pref("quiet_start"), pref("quiet_end")):
        return SILENT

    return SHOW


# --------------------------------------------------------------------------- #
# self-test: python rules.py
# --------------------------------------------------------------------------- #

WA = "net.whatsapp.WhatsApp"
SMS = "com.apple.MobileSMS"
SHOP = "com.myntra.Myntra"

_OFF = {"app_filter_mode": "off", "app_allowlist": [], "app_blocklist": [],
        "priority_apps": [], "quiet_enabled": False, "quiet_start": "22:00",
        "quiet_end": "07:00", "keyword_rules": []}


def _at(hour, minute=0):
    """A timestamp at local hour:minute today."""
    now = time.localtime()
    return time.mktime((now.tm_year, now.tm_mon, now.tm_mday, hour, minute,
                        0, 0, 0, -1))


CASES = [
    # (label, settings, kwargs, expected)
    ("default shows", {}, {"bundle_id": WA}, SHOW),

    ("blocklist silences", {"app_filter_mode": "blocklist",
                            "app_blocklist": [SHOP]},
     {"bundle_id": SHOP}, SILENT),
    ("blocklist spares others", {"app_filter_mode": "blocklist",
                                 "app_blocklist": [SHOP]},
     {"bundle_id": WA}, SHOW),
    ("allowlist admits", {"app_filter_mode": "allowlist",
                          "app_allowlist": [WA]}, {"bundle_id": WA}, SHOW),
    ("allowlist excludes", {"app_filter_mode": "allowlist",
                            "app_allowlist": [WA]}, {"bundle_id": SHOP},
     SILENT),
    # An empty allow-list is a half-finished setting, not an instruction to
    # silence the entire phone.
    ("empty allowlist is off", {"app_filter_mode": "allowlist",
                                "app_allowlist": []},
     {"bundle_id": SHOP}, SHOW),

    ("quiet hours silence", {"quiet_enabled": True},
     {"bundle_id": WA, "now": _at(23, 30)}, SILENT),
    ("quiet hours wrap past midnight", {"quiet_enabled": True},
     {"bundle_id": WA, "now": _at(2, 0)}, SILENT),
    ("outside quiet hours", {"quiet_enabled": True},
     {"bundle_id": WA, "now": _at(12, 0)}, SHOW),
    ("priority beats quiet hours", {"quiet_enabled": True,
                                    "priority_apps": [WA]},
     {"bundle_id": WA, "now": _at(23, 30)}, SHOW),

    ("keyword forces silent", {"keyword_rules": [{"pattern": "sale",
                                                  "action": SILENT}]},
     {"bundle_id": WA, "body": "Huge SALE today"}, SILENT),
    ("keyword forces drop", {"keyword_rules": [{"pattern": "unsubscribe",
                                                "action": DROP}]},
     {"bundle_id": WA, "body": "click to unsubscribe"}, DROP),
    ("keyword beats blocklist", {"app_filter_mode": "blocklist",
                                 "app_blocklist": [SHOP],
                                 "keyword_rules": [{"pattern": "delivered",
                                                    "action": SHOW}]},
     {"bundle_id": SHOP, "body": "Your order was delivered"}, SHOW),
    ("regex chars are literal", {"keyword_rules": [{"pattern": "[unclosed",
                                                    "action": DROP}]},
     {"bundle_id": WA, "body": "anything"}, SHOW),
    ("literal match on punctuation", {"keyword_rules": [{"pattern": "50% off",
                                                         "action": SILENT}]},
     {"bundle_id": SHOP, "body": "Get 50% off now"}, SILENT),
    ("a dot is not a wildcard", {"keyword_rules": [{"pattern": "a.c",
                                                    "action": DROP}]},
     {"bundle_id": WA, "body": "abc"}, SHOW),

    # the safety rail
    ("call beats blocklist", {"app_filter_mode": "blocklist",
                              "app_blocklist": ["com.apple.mobilephone"]},
     {"bundle_id": "com.apple.mobilephone", "style": "call"}, SHOW),
    ("call beats quiet hours", {"quiet_enabled": True},
     {"style": "call", "now": _at(3, 0)}, SHOW),
    ("call beats a drop keyword", {"keyword_rules": [{"pattern": "mum",
                                                      "action": DROP}]},
     {"style": "call", "app": "Phone", "title": "Mum"}, SHOW),

    ("equal quiet window is off", {"quiet_enabled": True,
                                   "quiet_start": "08:00",
                                   "quiet_end": "08:00"},
     {"bundle_id": WA, "now": _at(8, 30)}, SHOW),
]


def _selftest() -> int:
    failures = 0
    for label, overrides, kwargs, expected in CASES:
        settings = dict(_OFF)
        settings.update(overrides)
        got = decide(settings=settings, **kwargs)
        ok = got == expected
        failures += 0 if ok else 1
        print("%s %-32s got %-7s want %s"
              % ("ok  " if ok else "FAIL", label, got, expected))
    print("\n%d/%d passed" % (len(CASES) - failures, len(CASES)))
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
