"""
otp.py - find the one-time code in a notification.

ANCS hands us the title and body as plain text, so this is pure string work.
No iOS involvement, and it works for any app that sends codes as text.

The hard part is not finding digits, it is not finding the WRONG digits. A
transaction alert, a delivery update and an OTP all look like "some words and
a number". So a digit run only counts as a code when an OTP-ish word sits
near it, and it is thrown out when a money or reference marker sits directly
in front of it.

Precision beats recall here. A missing Copy button is invisible; a Copy
button that puts your account balance on the clipboard is the kind of bug you
discover at a payment page.
"""

from __future__ import annotations

import re

MIN_LEN = 4
MAX_LEN = 8

# How far a keyword can sit from the digits and still be talking about them.
# 44 covers "your one-time password for logging in to Flipkart is 152634"
# without letting a keyword in one sentence claim a number in the next.
MAX_GAP = 44

STRONG_WEIGHT = 100
WEAK_WEIGHT = 45

# How far back to look for a label that owns the number ("Rs. 4,999",
# "a/c XX1234"). Deliberately short: these words only disqualify when they
# are immediately in front of the digits, because "OTP to confirm your
# order is 8821" must still work.
LEFT_WINDOW = 16

# Phrases that on their own mean "the number beside me is a login code".
STRONG = (
    "otp", "o.t.p", "one time password", "one-time password",
    "one time passcode", "one-time passcode", "one time code",
    "one-time code", "onetime code", "verification code", "verify code",
    "security code", "access code", "login code", "log-in code",
    "signin code", "sign-in code", "authentication code", "auth code",
    "confirmation code", "activation code", "passcode", "2fa", "mfa",
    "two factor", "two-factor",
)

# Only enough on their own if nothing contradicts them.
WEAK = ("code", "pin", "password", "token", "verify", "verification")

# A number wearing one of these labels is money or a reference number.
DISQUALIFY = (
    "rs.", "rs ", "inr", "usd", "eur", "gbp", "aed", "\u20b9", "$",
    "amount", "balance", "debited", "credited", "credit", "debit",
    "txn", "transaction", "transfer", "paid", "payment",
    "a/c", "acct", "account", "ending", "ref no", "ref:", "reference",
    "order", "invoice", "awb", "tracking", "consignment", "booking",
    "pnr", "ticket", "coupon", "promo", "discount", "cashback",
    "referral", "gst", "emi", "due", "call", "dial", "contact",
)

# A run of digits that is not glued to other letters or digits. The lookarounds
# are what reject a masked account ("XX1234"), a long reference ("120250918")
# and a code with a trailing suffix ("1234abc"), while still allowing a
# prefixed code ("G-152634") because the hyphen is not alphanumeric.
_CANDIDATE = re.compile(
    r"(?<![0-9A-Za-z])(\d{%d,%d})(?![0-9A-Za-z])" % (MIN_LEN, MAX_LEN)
)


def _gap(start: int, end: int, k_start: int, k_end: int) -> int:
    """Characters between a keyword span and a candidate span. 0 if they touch."""
    if k_end <= start:
        return start - k_end
    if k_start >= end:
        return k_start - end
    return 0


def _score(lowered: str, start: int, end: int) -> tuple[int, int]:
    """
    How strongly the surrounding words claim this number is a code, as
    (strong, weak).

    Nearest keyword wins, and distance is subtracted so that in "OTP 1234 is
    valid for order 998877" the 1234 outscores the 998877. The two tiers are
    kept apart because only an explicit word like "OTP" is trusted enough to
    overrule a money or reference label.
    """
    scores = [0, 0]
    for tier, (words, weight) in enumerate(
            ((STRONG, STRONG_WEIGHT), (WEAK, WEAK_WEIGHT))):
        for word in words:
            position = lowered.find(word)
            while position != -1:
                gap = _gap(start, end, position, position + len(word))
                if gap <= MAX_GAP:
                    scores[tier] = max(scores[tier], weight - gap)
                position = lowered.find(word, position + 1)
    return scores[0], scores[1]


def _labelled_as_other(lowered: str, start: int) -> bool:
    """True when a money or reference word sits right in front of the digits."""
    left = lowered[max(0, start - LEFT_WINDOW):start]
    return any(marker in left for marker in DISQUALIFY)


def find(*texts: str | None) -> str | None:
    """
    The one-time code in these strings, or None.

    Arguments are searched as one blob in the order given, so pass the body
    before the title - the code almost always lives in the body, and joining
    them lets a keyword in the title vouch for digits in the body.
    """
    blob = " ".join(text for text in texts if text).strip()
    if not blob:
        return None
    lowered = blob.lower()

    winner = None
    best = 0
    for match in _CANDIDATE.finditer(blob):
        start, end = match.span(1)
        strong, weak = _score(lowered, start, end)
        # A money or reference label in front of the digits kills a candidate
        # that only had a vague word like "code" going for it. An explicit
        # "OTP" overrules the label, because "OTP to confirm your order is
        # 8821" reads as a code to a human and the argmax still prefers a
        # better-placed candidate if the message really does carry both.
        score = strong if _labelled_as_other(lowered, start) else max(strong,
                                                                     weak)
        if score > best:
            winner, best = match.group(1), score
    return winner


def find_in_item(item) -> str | None:
    """Convenience for a store.Item snapshot or the dict a toast is built from."""
    if item is None:
        return None
    if isinstance(item, dict):
        return find(item.get("body"), item.get("title"))
    return find(getattr(item, "body", None), getattr(item, "title", None))


# --------------------------------------------------------------------------- #
# self-test: python otp.py
# --------------------------------------------------------------------------- #

CASES = [
    # (body, expected)
    ("LOGIN to your Flipkart account using OTP 152634. DO NOT SHARE", "152634"),
    ("152634 is your OTP for login. Valid for 10 minutes.", "152634"),
    ("Your OTP is 4821", "4821"),
    ("OTP: 8821", "8821"),
    ("G-152634 is your Google verification code", "152634"),
    ("Use 739201 to verify your phone number", "739201"),
    ("Your one-time password for logging in is 152634", "152634"),
    ("<#> 5512 is your WhatsApp code", "5512"),
    ("Your Amazon security code is 903112. Do not share.", "903112"),
    ("OTP to confirm your order is 8821", "8821"),
    ("Enter passcode 44219 to continue", "44219"),
    ("Your 2FA token is 664120", "664120"),
    # both a code and a transaction in one message: the code must win
    ("Your OTP is 4821. Rs 5000 debited from a/c 9988", "4821"),

    # things that must NOT produce a Copy button
    ("Rs. 4999 debited from a/c XX1234 on 18-09-26", None),
    ("Your order 40281773 has been shipped", None),
    ("Rs 152634 credited to your account", None),
    ("Meeting moved to 1430 tomorrow", None),
    ("Use coupon code SAVE50 for 20% off orders above 1499", None),
    ("Your package AWB 77219043 is out for delivery", None),
    ("Hey, call me back on 9876543210", None),
    ("Balance in a/c is 15263", None),
    ("", None),
    (None, None),
]


def _selftest() -> int:
    failures = 0
    for body, expected in CASES:
        got = find(body)
        flag = "ok  " if got == expected else "FAIL"
        if got != expected:
            failures += 1
        print(f"{flag} {str(got):>8}  (want {str(expected):>8})  {body!r}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
