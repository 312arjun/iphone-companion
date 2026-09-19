"""
Apple Notification Center Service (ANCS) protocol layer.

This module is deliberately transport-agnostic. It knows how to:
  - identify the ANCS GATT characteristics,
  - parse a "Notification Source" packet (the 8-byte header iOS pushes),
  - build a "Get Notification Attributes" command for the Control Point,
  - reassemble a fragmented "Data Source" response into title/message text.

Nothing in here touches Bluetooth or the serial port. That means when we
fall back to the ESP32 bridge (Path B), the ESP32 does the GATT work and
hands us the already-parsed fields, and we can reuse all the display logic
without changing this file.
"""

import struct

# --- GATT UUIDs (lowercase, as bleak expects) ---------------------------------
ANCS_SERVICE        = "7905f431-b5ce-4e99-a40f-4b1e122d00d0"
NOTIFICATION_SOURCE = "9fbf120d-6301-42d9-8c58-25e699a21dbd"  # notify
CONTROL_POINT       = "69d1d8f3-45e1-49a8-9821-9bbdfdaad9d9"  # write w/ response
DATA_SOURCE         = "22eac6e9-24d6-4bb5-be44-b36ace7c7bfb"  # notify

# --- Notification Source: EventID (byte 0) ------------------------------------
EVENT_ADDED    = 0
EVENT_MODIFIED = 1
EVENT_REMOVED  = 2

# --- Notification Source: EventFlags (byte 1, bitmask) ------------------------
FLAG_SILENT          = 1 << 0
FLAG_IMPORTANT       = 1 << 1
FLAG_PRE_EXISTING    = 1 << 2
FLAG_POSITIVE_ACTION = 1 << 3
FLAG_NEGATIVE_ACTION = 1 << 4

# --- Notification Source: CategoryID (byte 2) ---------------------------------
CATEGORIES = {
    0:  "Other",       1:  "Incoming Call", 2:  "Missed Call",
    3:  "Voicemail",   4:  "Social",        5:  "Schedule",
    6:  "Email",       7:  "News",          8:  "Health & Fitness",
    9:  "Business",    10: "Location",      11: "Entertainment",
    12: "Active Call",
}

# --- Control Point command + attribute IDs ------------------------------------
CMD_GET_NOTIFICATION_ATTRIBUTES = 0
CMD_GET_APP_ATTRIBUTES          = 1
CMD_PERFORM_NOTIFICATION_ACTION = 2

# --- Perform Notification Action: ActionID ------------------------------------
# For an Incoming Call these are literally answer / decline. For most other
# categories positive = open the app, negative = clear the notification.
ACTION_POSITIVE = 0
ACTION_NEGATIVE = 1

ATTR_APP_ID     = 0   # no length parameter
ATTR_TITLE      = 1   # needs 2-byte max length
ATTR_SUBTITLE   = 2   # needs 2-byte max length
ATTR_MESSAGE    = 3   # needs 2-byte max length
ATTR_MESSAGE_SZ = 4
ATTR_DATE       = 5   # no length parameter
ATTR_POS_LABEL  = 6   # no length parameter
ATTR_NEG_LABEL  = 7   # no length parameter

ATTR_NAMES = {
    0: "AppIdentifier", 1: "Title", 2: "Subtitle", 3: "Message",
    4: "MessageSize", 5: "Date", 6: "PositiveActionLabel",
    7: "NegativeActionLabel",
}

# Control Point failures surface as a GATT write error with these codes.
ANCS_ERRORS = {
    0xA0: "Unknown command",
    0xA1: "Invalid command (malformed attribute list)",
    0xA2: "Invalid parameter (the notification is usually already gone)",
    0xA3: "Action failed",
}


def error_name(exc) -> str:
    """Pull an ANCS error code out of a bleak protocol error, if present."""
    for part in getattr(exc, "args", ()):
        if isinstance(part, int) and part in ANCS_ERRORS:
            return f"{part:#04x} {ANCS_ERRORS[part]}"
    return str(exc)

# A small friendly-name map for the most common iOS app bundle IDs.
# Anything not listed just shows its bundle id, which is still readable.
APP_NAMES = {
    "com.apple.MobileSMS":       "Messages",
    "com.apple.mobilephone":     "Phone",
    "com.apple.mobilemail":      "Mail",
    "com.apple.mobilecal":       "Calendar",
    "com.apple.mobileslideshow": "Photos",
    "net.whatsapp.WhatsApp":     "WhatsApp",
    "com.burbn.instagram":       "Instagram",
    "com.facebook.Facebook":     "Facebook",
    "com.hammerandchisel.discord": "Discord",
    "com.tinyspeck.chatlyio":    "Slack",
    "com.google.Gmail":          "Gmail",
    "com.microsoft.Office.Outlook": "Outlook",
    "com.toyopagroup.picaboo":   "Snapchat",
    "com.atebits.Tweetie2":      "X / Twitter",
    "ph.telegra.Telegraph":      "Telegram",
    "com.apple.facetime":        "FaceTime",
    "com.apple.reminders":       "Reminders",
    "com.apple.mobileaddressbook": "Contacts",
    "com.google.ios.youtube":    "YouTube",
    "com.zhiliaoapp.musically":  "TikTok",
    "com.linkedin.LinkedIn":     "LinkedIn",
    "com.ubercab.UberClient":    "Uber",
    "com.google.Maps":           "Google Maps",
    "com.spotify.client":        "Spotify",
    "com.amazon.Amazon":         "Amazon",
    "com.amazon.AmazonIN":       "Amazon",
    "com.amazon.aiv.AIVApp":     "Prime Video",
    "com.dominosin.olo":         "Domino's",
    "com.myntra.Myntra":         "Myntra",
    "com.bigbasket.mobileapp":   "BigBasket",
    "com.urbanclap.customer":    "Urban Company",
    "com.payu.citrusapp":        "PayU",
    "in.org.npci.ios.upiapp":    "BHIM",
    "com.google.ios.youtube":    "YouTube",
    "com.apple.mobilenotes":     "Notes",
    "com.apple.Health":          "Health",
    "com.apple.weather":         "Weather",
    "com.apple.AppStore":        "App Store",
    "com.apple.Passbook":        "Wallet",
    "com.swiggy.SwiggyApp":      "Swiggy",
    "com.zomato.zomato":         "Zomato",
    "com.phonepe.PhonePeApp":    "PhonePe",
    "com.google.paisa.user":     "Google Pay",
    "com.gmail.ios":             "Gmail",
    "com.netflix.Netflix":       "Netflix",
    "com.hotstar.hotstarx":      "JioHotstar",
}

# Bundle-id segments that carry no brand meaning, dropped when deriving a
# display name for an app we have no entry for.
_NOISE = {
    "com", "org", "net", "io", "co", "in", "uk", "de", "app", "apps",
    "ios", "iphone", "mobile", "mobileapp", "client", "customer", "user",
    "inc", "ltd", "the", "my", "go",
}


def derive_app_name(bundle_id: str) -> str:
    """
    Make something readable out of an unknown bundle id.

    Showing the raw id as a notification header looks broken -
    "com.dominosin.olo" is not an app name. Drop the meaningless segments and
    take the most distinctive one that is left, keeping its own capitalisation
    when the developer already provided some ("Myntra", not "myntra").
    """
    parts = [p for p in (bundle_id or "").split(".") if p]
    if not parts:
        return "iPhone"
    candidates = [p for p in parts if p.lower() not in _NOISE] or parts
    best = max(candidates, key=len)
    return best if any(c.isupper() for c in best) else best.capitalize()


def friendly_app_name(bundle_id: str) -> str:
    known = APP_NAMES.get(bundle_id)
    if known:
        return known
    return derive_app_name(bundle_id) if bundle_id else "iPhone"


def parse_notification_source(data: bytes):
    """
    Parse the 8-byte Notification Source packet.
    Returns a dict, or None if the packet is too short.
    """
    if len(data) < 8:
        return None
    event_id, flags, category, category_count, uid = struct.unpack("<4BI", data[:8])
    return {
        "event_id": event_id,
        "flags": flags,
        "category": category,
        "category_name": CATEGORIES.get(category, f"Category {category}"),
        "category_count": category_count,
        "uid": uid,
        "silent": bool(flags & FLAG_SILENT),
        "positive": bool(flags & FLAG_POSITIVE_ACTION),
        "negative": bool(flags & FLAG_NEGATIVE_ACTION),
    }


def build_get_attributes(uid: int,
                         flags: int = 0,
                         title_len: int = 64,
                         subtitle_len: int = 64,
                         message_len: int = 512):
    """
    Build a Control Point "Get Notification Attributes" command and return
    (payload, expected_attribute_ids).

    Only Title, Subtitle and Message carry a 2-byte max length. AppIdentifier,
    Date and the two action labels must be sent as a bare attribute id -
    appending a length to those makes iOS read the length bytes as two more
    attribute requests, which corrupts the whole response.

    The action labels are requested only when the Notification Source flags
    advertised them; asking for an absent attribute is rejected outright.
    """
    ids = [ATTR_APP_ID, ATTR_TITLE, ATTR_SUBTITLE, ATTR_MESSAGE, ATTR_DATE]

    payload = bytearray()
    payload.append(CMD_GET_NOTIFICATION_ATTRIBUTES)
    payload += struct.pack("<I", uid)
    payload.append(ATTR_APP_ID)                                  # no length
    payload.append(ATTR_TITLE);    payload += struct.pack("<H", title_len)
    payload.append(ATTR_SUBTITLE); payload += struct.pack("<H", subtitle_len)
    payload.append(ATTR_MESSAGE);  payload += struct.pack("<H", message_len)
    payload.append(ATTR_DATE)                                    # no length

    if flags & FLAG_POSITIVE_ACTION:
        payload.append(ATTR_POS_LABEL)                           # no length
        ids.append(ATTR_POS_LABEL)
    if flags & FLAG_NEGATIVE_ACTION:
        payload.append(ATTR_NEG_LABEL)                           # no length
        ids.append(ATTR_NEG_LABEL)

    return bytes(payload), ids


def build_perform_action(uid: int, action_id: int) -> bytes:
    """
    Build a Control Point "Perform Notification Action" command.

    Layout: CommandID(1) | NotificationUID(uint32 LE) | ActionID(1)

    Only valid while the notification is live on the phone, and only if the
    Notification Source flags advertised the action (see "positive"/"negative"
    from parse_notification_source). iOS answers an invalid UID with an error
    on the Control Point write rather than doing nothing.
    """
    return (bytes([CMD_PERFORM_NOTIFICATION_ACTION])
            + struct.pack("<I", uid)
            + bytes([action_id]))


class DataSourceAssembler:
    """
    Reassembles Data Source notifications. iOS may split a long response
    across several GATT notifications, so we buffer bytes and only emit a
    result once every requested attribute has fully arrived.

    The requested attribute set varies per notification (the action labels are
    only asked for when advertised), so call expect(uid, ids) with the ids
    returned by build_get_attributes before writing the request. Without it,
    DEFAULT_ATTRS is assumed.

    Response layout:
        [0]      CommandID (0)
        [1..4]   NotificationUID (uint32 LE)
        then repeated: AttributeID(1) | Length(2 LE) | Value(Length bytes)
    """

    DEFAULT_ATTRS = (ATTR_APP_ID, ATTR_TITLE, ATTR_SUBTITLE, ATTR_MESSAGE)
    MAX_PENDING = 64

    def __init__(self, expected_attrs=None):
        self.buf = bytearray()
        self.default = tuple(expected_attrs) if expected_attrs else self.DEFAULT_ATTRS
        self.expected: dict[int, tuple] = {}

    def expect(self, uid: int, attr_ids) -> None:
        self.expected[uid] = tuple(attr_ids)
        while len(self.expected) > self.MAX_PENDING:
            self.expected.pop(next(iter(self.expected)))

    def feed(self, data: bytes):
        self.buf += data
        if len(self.buf) < 5:
            return None

        uid = struct.unpack("<I", self.buf[1:5])[0]
        wanted = self.expected.get(uid, self.default)

        attrs = {}
        i = 5
        while len(attrs) < len(wanted):
            if i + 3 > len(self.buf):
                return None                      # need the attr header
            attr_id = self.buf[i]
            if attr_id > ATTR_NEG_LABEL:
                self.buf = bytearray()           # malformed: resync rather than
                return None                      # desync every later response
            length = struct.unpack("<H", self.buf[i + 1:i + 3])[0]
            if i + 3 + length > len(self.buf):
                return None                      # need the rest of the value
            value = self.buf[i + 3:i + 3 + length].decode("utf-8", errors="replace")
            attrs[attr_id] = value
            i += 3 + length

        self.buf = bytearray()                   # ready for the next notification
        self.expected.pop(uid, None)
        return {
            "uid": uid,
            "app_id":   attrs.get(ATTR_APP_ID, ""),
            "title":    attrs.get(ATTR_TITLE, ""),
            "subtitle": attrs.get(ATTR_SUBTITLE, ""),
            "message":  attrs.get(ATTR_MESSAGE, ""),
            "date":     attrs.get(ATTR_DATE, ""),
            "positive_label": attrs.get(ATTR_POS_LABEL, ""),
            "negative_label": attrs.get(ATTR_NEG_LABEL, ""),
        }
