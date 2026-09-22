"""
theme.py - palette, radii and fonts for the Qt UI.

The dashboard palette is sampled off the reference mock: a near-black canvas
with a faint blue cast, cards one step lighter with a hairline border, system
green as the only saturated colour, and a lot of breathing room.

The toast styling lives in toast_sheet() and follows the Apple-style toast
spec: one glass panel, a thin low-opacity light border, SF Pro with Segoe UI
as the Windows fallback, near-white primary text and muted grey secondary
text. The spec is drawn at 720x150 and scaled down here - see TOAST_SCALE.

FONT_FAMILY is resolved at runtime - the first attempt hardcoded a family that
Qt could not find, which silently degraded every label.
"""

from __future__ import annotations

FONT_FAMILY = "Segoe UI"
# Order matters, and the first version got it wrong in a way that is easy to
# miss: it asked for "Segoe UI Variable Display" first.
#
# Segoe UI Variable is an optical-size family. Small is drawn for 8-12pt,
# Text for 12-18pt, Display for 24pt and up. Display has thin strokes and
# tight sidebearings meant for headlines, so at the 10-13px this UI actually
# uses it renders soft and spindly - the "stretched bitmap" look.
#
# Static Segoe UI leads instead, because the whole variable family carries
# reduced TrueType hinting on the assumption of a high-DPI screen. At around
# 80-96 physical DPI hinting is exactly what keeps small text crisp, so the
# hinted static face is the better default and Variable Text is the fallback
# for anywhere it is missing.
FONT_CANDIDATES = (
    "Segoe UI",
    "Segoe UI Variable Text",
    "Inter",
    "Arial",
)

# canvas
# --------------------------------------------------------------------------- #
# palettes
#
# Every colour the app uses lives in one of these two dicts and nowhere else.
# apply_mode() copies the chosen one onto this module's globals, so the rest
# of the codebase keeps reading theme.TEXT, theme.CARD and so on with no idea
# a mode exists. That only works because those reads happen at call time,
# inside functions - a module that did `TEXT = theme.TEXT` at import would
# freeze the dark value, so nothing does.
#
# The light palette is not the dark one inverted. Inverting gives muddy
# greys and an accent that vibrates against white, so the surfaces are
# warm-neutral, the borders carry the separation that shadow carries in dark
# mode, and the accent is darkened for contrast against pale backgrounds.
# --------------------------------------------------------------------------- #

DARK = {
    "BG": "#040F1A",
    "BG_SIDEBAR": "#061322",
    "BG_SIDEBAR_HEADER": "#08192B",
    "CARD": "#0A1A2B",
    "CARD_HOVER": "#0E2438",
    "CARD_SUNK": "#071522",
    "BORDER": "#12304A",
    "BORDER_SOFT": "#0C2237",
    "TEXT": "#EAF4FF",
    "TEXT_DIM": "#8FB0CC",
    "TEXT_FAINT": "#5B7C99",
    "ACCENT": "#1B9DF0",
    "GREEN": "#22E584",
    "RED": "#FF4D5E",
    "AMBER": "#FFB84D",
    "TOAST_BG": "#0A1A2B",
    "TOAST_BORDER": "#173A58",
    "TOAST_TEXT": "#EAF4FF",
    "TOAST_TEXT_DIM": "#8FB0CC",
    "SWITCH_OFF": "#1C3951",
}

LIGHT = {
    "BG": "#FBFDFF",
    "BG_SIDEBAR": "#F2F8FE",
    "BG_SIDEBAR_HEADER": "#E6F1FC",
    "CARD": "#FFFFFF",
    "CARD_HOVER": "#E8F2FD",
    "CARD_SUNK": "#F4F8FC",
    "BORDER": "#D3E3F2",
    "BORDER_SOFT": "#E4EDF6",
    "TEXT": "#0A1A2B",
    "TEXT_DIM": "#4A6377",
    "TEXT_FAINT": "#7C93A6",
    "ACCENT": "#0A6FD8",
    "GREEN": "#12A65A",
    "RED": "#D93B4A",
    "AMBER": "#B8730A",
    "TOAST_BG": "#0A1A2B",
    "TOAST_BORDER": "#173A58",
    "TOAST_TEXT": "#EAF4FF",
    "TOAST_TEXT_DIM": "#8FB0CC",
    "SWITCH_OFF": "#C3D4E2",
}

MODE = "dark"


def apply_mode(mode: str) -> str:
    """
    Switch palette. Returns the mode actually applied.

    Call before sheet(); the stylesheet is built from these globals, so the
    order matters. Anything other than "light" falls back to dark rather
    than half-applying an unknown palette.
    """
    global MODE
    MODE = "light" if str(mode).lower() == "light" else "dark"
    for name, value in (LIGHT if MODE == "light" else DARK).items():
        globals()[name] = value
    globals()["ACTION_COLOURS"] = {"positive": globals()["GREEN"],
                                   "negative": globals()["RED"],
                                   "neutral": globals()["ACCENT"]}
    return MODE


apply_mode("dark")          # populate the globals at import

# Declared explicitly as well, even though apply_mode() has just set them.
# Without these, every colour name inside sheet() is invisible to static
# analysis - pyflakes reported sixty "undefined name" errors and, worse,
# would no longer catch a real typo like {CARD_HOVR}. Assigning from DARK
# keeps that check working; apply_mode() overwrites them on a switch.
BG = DARK["BG"]
BG_SIDEBAR = DARK["BG_SIDEBAR"]
BG_SIDEBAR_HEADER = DARK["BG_SIDEBAR_HEADER"]
CARD = DARK["CARD"]
CARD_HOVER = DARK["CARD_HOVER"]
CARD_SUNK = DARK["CARD_SUNK"]
BORDER = DARK["BORDER"]
BORDER_SOFT = DARK["BORDER_SOFT"]
TEXT = DARK["TEXT"]
TEXT_DIM = DARK["TEXT_DIM"]
TEXT_FAINT = DARK["TEXT_FAINT"]
ACCENT = DARK["ACCENT"]
GREEN = DARK["GREEN"]
RED = DARK["RED"]
AMBER = DARK["AMBER"]
TOAST_BG = DARK["TOAST_BG"]
TOAST_BORDER = DARK["TOAST_BORDER"]
TOAST_TEXT = DARK["TOAST_TEXT"]
TOAST_TEXT_DIM = DARK["TOAST_TEXT_DIM"]
SWITCH_OFF = DARK["SWITCH_OFF"]
ACTION_COLOURS = {"positive": GREEN, "negative": RED, "neutral": ACCENT}

RADIUS = 16
RADIUS_SM = 11

# The toast spec is drawn at 720x150. That is far larger than a desktop
# notification wants to be, so every measurement is scaled by these two
# factors - geometry harder than type, because 8px text stops being readable
# long before a 40px icon stops being recognisable. The design is unchanged;
# only the scale is.
TOAST_SCALE = 0.56
TOAST_TEXT_SCALE = 0.68


def ts(value: float) -> int:
    """Scale a geometry measurement from the 720px spec."""
    return max(1, round(value * TOAST_SCALE))


def tt(value: float) -> int:
    """Scale a font size from the spec."""
    return max(8, round(value * TOAST_TEXT_SCALE))


# Tile size. The spec's 56 (31px scaled) was too small next to three lines of
# text; the full text-block height (64px) was too big. 86 in spec space lands
# at 48px, which is what the old shadow-inset PNG happened to render at and
# reads correctly against App Store artwork.
TOAST_ICON = ts(86)
TOAST_ICON_RADIUS = round(TOAST_ICON * 0.24)     # Apple-ish squircle
TOAST_AVATAR_RADIUS = TOAST_ICON // 2

# The Dial pill. Its radius is half its height so it is a true capsule -
# quoting the spec's 28px against a 31px-high button left Qt clamping it into
# something closer to a rounded rectangle.
TOAST_DIAL_W = ts(125)
TOAST_DIAL_H = ts(62)
TOAST_DIAL_RADIUS = TOAST_DIAL_H // 2


def resolve_fonts() -> None:
    """Pick the best family actually installed. Call once, after QApplication."""
    global FONT_FAMILY
    try:
        from PySide6.QtGui import QFontDatabase
        available = set(QFontDatabase.families())
        for name in FONT_CANDIDATES:
            if name in available:
                FONT_FAMILY = name
                return
    except Exception:
        pass


def sheet() -> str:
    return f"""
    QWidget {{
        background: {BG};
        color: {TEXT};
        font-family: "{FONT_FAMILY}";
        font-size: 13px;
    }}
    QLabel {{ background: transparent; }}
    QFrame#card {{
        background: {CARD};
        border: 1px solid {BORDER_SOFT};
        border-radius: {RADIUS}px;
    }}
    QFrame#sidebar {{
        background: {BG_SIDEBAR};
        border: none;
        border-right: 1px solid {BORDER_SOFT};
    }}
    /* The brand band spans the full sidebar width, so it lives outside the
       padded body column - see Dashboard._sidebar. The body itself has to be
       transparent or it would inherit the QWidget rule above and paint the
       canvas colour over the sidebar. */
    QWidget#brandRow {{
        background: {BG_SIDEBAR_HEADER};
        border: none;
        border-bottom: 1px solid {BORDER_SOFT};
    }}
    QWidget#sidebarBody {{ background: transparent; }}
    QFrame#titlebar {{ background: {BG}; border: none; }}

    /* Device Info grid cell. Its own sunk surface and border, which is what
       separates it from InfoRow's transparent line inside a card. */
    QFrame#infoTile {{
        background: {CARD_SUNK};
        border: 1px solid {BORDER_SOFT};
        border-radius: 12px;
    }}
    QFrame#infoTile:hover {{ border: 1px solid {BORDER}; }}
    QFrame#infoTileIcon {{
        background: {CARD_HOVER};
        border: 1px solid {BORDER_SOFT};
        border-radius: 10px;
    }}

    QFrame#activityRow {{
        background: transparent;
        border: none;
        border-radius: 7px;
    }}
    QFrame#activityRow:hover {{ background: {CARD_HOVER}; }}

    /* A card's own header icon, bigger and more lit than the grid tiles. */
    QFrame#sectionIcon {{
        background: {CARD_HOVER};
        border: 1px solid {BORDER};
        border-radius: 11px;
    }}

    /* Stating a limitation in place. Accent-tinted border rather than
       amber or red: read-only is a fact about the protocol, not a warning
       and not an error. */
    QFrame#infoBanner {{
        background: {CARD_SUNK};
        border: 1px solid {BORDER};
        border-left: 3px solid {ACCENT};
        border-radius: 12px;
    }}

    /* The three facts beside the phone on Overview. Sunk like the Device
       Info grid cells, so the two pages describe the phone the same way. */
    QFrame#stackRow {{ background: transparent; border: none; }}
    QFrame#factTile {{
        background: {CARD_SUNK};
        border: 1px solid {BORDER_SOFT};
        border-radius: 11px;
    }}
    /* Same surface, but these are clickable, so they respond to the cursor
       and lift toward the accent on hover. */
    QFrame#actionTile {{
        background: {CARD_SUNK};
        border: 1px solid {BORDER_SOFT};
        border-radius: 11px;
    }}
    QFrame#actionTile:hover {{
        background: {CARD_HOVER};
        border: 1px solid {ACCENT};
    }}

    QFrame#titleBar {{
        background: {ACCENT};
        border: none;
        border-radius: 2px;
    }}
    /* The save confirmation. Green-tinted when it worked, red when the
       write failed - the two must not look alike, or a silent revert on the
       next start comes as a surprise. */
    QFrame#saveNotice {{
        background: {CARD_SUNK};
        border: 1px solid {GREEN};
        border-radius: 15px;
    }}
    QFrame#saveNotice[failed="true"] {{
        border: 1px solid {RED};
    }}

    QFrame#sourceChip {{
        background: {CARD_HOVER};
        border: 1px solid {BORDER};
        border-radius: 12px;
    }}

    /* Notification and call list rows. */
    QFrame#feedRow {{ background: transparent; border-radius: 12px; }}
    QFrame#feedRow:hover {{ background: {CARD_HOVER}; }}
    QFrame#callRow {{ background: transparent; border-radius: 10px; }}
    QFrame#callRow:hover {{ background: {CARD_HOVER}; }}

    QPushButton#filterPill {{
        background: {CARD_SUNK};
        border: 1px solid {BORDER_SOFT};
        border-radius: 9px;
        color: {TEXT_DIM};
        padding: 0 18px;
        font-size: 12px;
    }}
    QPushButton#filterPill:hover {{
        background: {CARD_HOVER};
        color: {TEXT};
    }}
    QPushButton#filterPill:checked {{
        background: {ACCENT};
        border: 1px solid {ACCENT};
        color: #FFFFFF;
        font-weight: 600;
    }}

    QLabel#silencedTag {{
        background: transparent;
        color: {AMBER};
        border: 1px solid {AMBER};
        border-radius: 8px;
        padding: 1px 7px;
        font-size: 10px;
        font-weight: 600;
    }}
    /* The resize grip is a bare child of the window, so without this it
       fills its rect with the canvas colour and reads as a patch over
       whatever it happens to sit on. It stays functional when transparent. */
    QSizeGrip#sizeGrip {{ background: transparent; border: none; }}

    /* Settings > Notification rules, and the Notifications search box. */
    QLineEdit#searchBox {{
        background: {CARD_SUNK};
        border: 1px solid {BORDER};
        border-radius: 9px;
        padding: 7px 11px;
        color: {TEXT};
        font-size: 13px;
    }}
    QLineEdit#searchBox:focus {{ border: 1px solid {ACCENT}; }}

    QListWidget#app_picker, QListWidget#priority_picker,
    QListWidget#ruleList {{
        background: {CARD_SUNK};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 4px;
        color: {TEXT};
        font-size: 12px;
        outline: none;
    }}
    QListWidget#app_picker::item, QListWidget#priority_picker::item,
    QListWidget#ruleList::item {{
        padding: 5px 6px;
        border-radius: 6px;
    }}
    QListWidget#app_picker::item:hover, QListWidget#priority_picker::item:hover,
    QListWidget#ruleList::item:hover {{ background: {CARD_HOVER}; }}
    QListWidget#app_picker::item:selected,
    QListWidget#priority_picker::item:selected,
    QListWidget#ruleList::item:selected {{
        background: {CARD_HOVER};
        color: {TEXT};
    }}

    QComboBox#pill {{
        background: {CARD_HOVER};
        border: 1px solid {BORDER};
        border-radius: 9px;
        padding: 5px 10px;
        color: {TEXT};
        font-size: 12px;
    }}
    QComboBox#pill:hover {{ border: 1px solid {ACCENT}; }}
    QComboBox#pill::drop-down {{ border: none; width: 18px; }}
    QComboBox#pill QAbstractItemView {{
        background: {CARD};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT};
        color: {TEXT};
        outline: none;
    }}
    QFrame#sunk {{
        background: {CARD_SUNK};
        border: 1px solid {BORDER_SOFT};
        border-radius: {RADIUS_SM}px;
    }}

    QPushButton#nav {{
        background: transparent;
        border: none;
        border-radius: {RADIUS_SM}px;
        padding: 11px 14px;
        text-align: left;
        color: {TEXT_DIM};
        font-size: 14px;
    }}
    QPushButton#nav:hover {{ background: {CARD}; color: {TEXT}; }}
    QPushButton#nav:checked {{
        background: {CARD_HOVER};
        color: {TEXT};
        font-weight: 600;
    }}

    QPushButton#tile {{
        background: {CARD_SUNK};
        border: 1px solid {BORDER_SOFT};
        border-radius: {RADIUS_SM}px;
        color: {TEXT};
        font-size: 12px;
        padding: 0;
    }}
    QPushButton#tile:hover {{ background: {CARD_HOVER}; border-color: {BORDER}; }}
    QPushButton#tile:pressed {{ background: {CARD}; }}

    QPushButton#ghost {{
        background: transparent; border: none;
        border-radius: 8px; padding: 4px;
    }}
    QPushButton#ghost:hover {{ background: {CARD_HOVER}; }}

    QPushButton#chrome {{
        background: transparent; border: none; border-radius: 6px;
    }}
    QPushButton#chrome:hover {{ background: {CARD_HOVER}; }}
    QPushButton#chromeClose:hover {{ background: {RED}; }}

    /* The transport play button. An accent ring over the card rather than
       a filled white disc: the disc read as the brightest thing on the page
       and pulled the eye away from the track it was meant to play. */
    QPushButton#round {{
        background: transparent;
        border: 2px solid {ACCENT};
        border-radius: 27px;
    }}
    QPushButton#round:hover {{
        background: {CARD_HOVER};
        border: 2px solid {ACCENT};
    }}
    QPushButton#round:pressed {{ background: {CARD_SUNK}; }}

    QPushButton#link {{
        background: transparent; border: none;
        color: {ACCENT}; font-size: 12px;
    }}
    QPushButton#link:hover {{ color: #4DA3FF; }}

    QPushButton#pill {{
        background: {CARD_SUNK};
        border: 1px solid {BORDER};
        border-radius: 15px;
        padding: 6px 14px;
        color: {TEXT};
        font-size: 12px;
    }}

    /* The one-time-code capsule on a notification row.
       Named FeedCopyButton rather than CopyButton because toast_sheet(),
       which is appended to this sheet, styles CopyButton for a banner-sized
       pill - a later rule of equal specificity would win and flatten this.

       Fully rounded (radius = half the 24px height) so it reads as an iOS
       capsule rather than a bordered field, with the digits in the accent
       colour: the number IS the affordance, so colouring it says "clickable"
       without adding a second control. */
    QPushButton#FeedCopyButton {{
        background: {CARD_SUNK};
        border: 1px solid {BORDER};
        border-radius: 12px;
        padding: 0px 13px;
        color: {ACCENT};
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.6px;
    }}
    QPushButton#FeedCopyButton:hover {{
        background: {ACCENT};
        border: 1px solid {ACCENT};
        color: #FFFFFF;
    }}
    QPushButton#FeedCopyButton:pressed {{
        background: {CARD_HOVER};
        border: 1px solid {ACCENT};
        color: {ACCENT};
    }}
    QPushButton#FeedCopyButton:focus {{ outline: none; }}

    QScrollArea {{ border: none; background: transparent; }}
    QSlider::groove:horizontal {{
        background: {CARD_SUNK};
        height: 6px; border-radius: 3px;
    }}
    QSlider::sub-page:horizontal {{
        background: {ACCENT}; height: 6px; border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {TEXT}; width: 14px; height: 14px;
        margin: -5px 0; border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover {{ background: #FFFFFF; }}

    QLineEdit {{
        background: {CARD_SUNK};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 8px 10px;
        color: {TEXT};
        selection-background-color: {ACCENT};
    }}
    QLineEdit:focus {{ border-color: {ACCENT}; }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 4px 2px 4px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER}; border-radius: 4px; min-height: 36px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #303945; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}

    QToolTip {{
        background: {CARD}; color: {TEXT}; border: 1px solid {BORDER};
        padding: 6px 8px; border-radius: 6px;
    }}
    """ + toast_sheet()


def toast_sheet() -> str:
    """
    Apple-style toast styling, per the toast QSS spec, scaled down by
    TOAST_SCALE / TOAST_TEXT_SCALE.

    Two notes on what QSS cannot do here, both handled in qt_toast.py:

      * There is no backdrop blur. The panel is a translucent top-level window
        with a thin light border, which is the closest match available without
        compositor-level work.
      * A top-level window's corners cannot be rounded by QSS - the square
        window edge shows through. So the window stays transparent and empty,
        and a child QFrame carries the panel styling.
    """
    return f"""
/* ============================================================
   iPhone Companion - Shared Apple-Style Toast
   ============================================================ */

QWidget#toastRoot {{ background: transparent; }}

QFrame#MissedCallToast,
QFrame#IncomingCallToast,
QFrame#ActiveCallToast,
QFrame#NotificationToast {{
    background-color: rgba(28, 30, 35, 242);
    border: 1px solid rgba(190, 205, 220, 80);
    border-radius: {ts(28)}px;
    padding: 0px;
}}

QWidget#ToastContent,
QWidget#ToastHeader {{
    background: transparent;
    border: none;
}}


/* ============================================================
   MISSED CALL TOAST
   ============================================================ */

QLabel#MissedCallIcon {{
    background-color: #32D74B;
    color: white;
    border: none;
    border-radius: {TOAST_ICON_RADIUS}px;
    padding: 0px;
}}

QLabel#MissedCallApp {{
    background: transparent; border: none;
    color: #9EA4AE;
    font-family: "SF Pro Text", "SF Pro Display", "Segoe UI";
    font-size: {tt(18)}px;
    font-weight: 400;
}}

QLabel#MissedCallTime {{
    background: transparent; border: none;
    color: #858B95;
    font-family: "SF Pro Text", "Segoe UI";
    font-size: {tt(15)}px;
    font-weight: 400;
}}

QLabel#MissedCallTitle {{
    background: transparent; border: none;
    color: #F5F5F7;
    font-family: "SF Pro Display", "SF Pro Text", "Segoe UI";
    font-size: {tt(28)}px;
    font-weight: 600;
}}

QLabel#MissedCallCaller {{
    background: transparent; border: none;
    color: #9EA4AE;
    font-family: "SF Pro Text", "SF Pro Display", "Segoe UI";
    font-size: {tt(21)}px;
    font-weight: 400;
}}

/* The missed-call Dial pill and the one-time-code pill are the same control
   in two contexts, so they share every selector below rather than carrying
   two copies of the same gradient that could drift apart. CopyButton differs
   only in width, which is measured in qt_toast because a code is wider than
   the word "Dial". */

QPushButton#DialButton, QPushButton#CopyButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 rgba(84, 89, 98, 225),
                                stop:1 rgba(58, 62, 70, 225));
    color: #F5F5F7;
    border: 1px solid rgba(255, 255, 255, 35);
    border-radius: {TOAST_DIAL_RADIUS}px;
    font-family: "SF Pro Text", "SF Pro Display", "Segoe UI";
    font-size: {tt(21)}px;
    font-weight: 500;
    padding: 0px;
}}

QPushButton#DialButton:hover, QPushButton#CopyButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 rgba(98, 104, 114, 238),
                                stop:1 rgba(70, 75, 84, 238));
    border: 1px solid rgba(255, 255, 255, 55);
}}

QPushButton#DialButton:pressed, QPushButton#CopyButton:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 rgba(62, 66, 74, 245),
                                stop:1 rgba(46, 50, 57, 245));
}}

QPushButton#DialButton:focus, QPushButton#CopyButton:focus {{
    outline: none;
}}


/* ============================================================
   INCOMING CALL TOAST
   ============================================================ */

QLabel#IncomingCallIcon {{
    background-color: #32D74B;
    color: white;
    border: none;
    border-radius: {TOAST_ICON_RADIUS}px;
}}

QLabel#IncomingCallApp {{
    background: transparent; border: none;
    color: #9EA4AE;
    font-family: "SF Pro Text", "SF Pro Display", "Segoe UI";
    font-size: {tt(18)}px;
    font-weight: 400;
}}

QLabel#IncomingCaller {{
    background: transparent; border: none;
    color: #F5F5F7;
    font-family: "SF Pro Display", "SF Pro Text", "Segoe UI";
    font-size: {tt(28)}px;
    font-weight: 600;
}}

QLabel#IncomingStatus {{
    background: transparent; border: none;
    color: #9EA4AE;
    font-family: "SF Pro Text", "SF Pro Display", "Segoe UI";
    font-size: {tt(21)}px;
    font-weight: 400;
}}

QLabel#CallerAvatar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #767A82, stop:1 #4E505A);
    border: none;
    border-radius: {TOAST_AVATAR_RADIUS}px;
    color: rgba(255, 255, 255, 235);
    font-family: "SF Pro Display", "Segoe UI";
    font-size: {tt(24)}px;
    font-weight: 600;
}}

/* Answer and Decline - flat colour, no gradient */

QPushButton#AnswerButton {{
    background-color: #32D74B;
    color: white;
    border: none;
    border-radius: {ts(32)}px;
}}

QPushButton#AnswerButton:hover   {{ background-color: #42E568; }}
QPushButton#AnswerButton:pressed {{ background-color: #28B94C; }}

QPushButton#DeclineButton {{
    background-color: #FF3B30;
    color: white;
    border: none;
    border-radius: {ts(32)}px;
}}

QPushButton#DeclineButton:hover   {{ background-color: #FF5147; }}
QPushButton#DeclineButton:pressed {{ background-color: #D92F27; }}

/* PNG-backed variants: assets/call-pickup.png and call-decline.png are the
   whole button, so there is nothing to draw behind them and no hover state -
   a ring or a tint just fights the artwork. The cursor is the affordance. */

QPushButton#AnswerButtonArt,
QPushButton#DeclineButtonArt,
QPushButton#AnswerButtonArt:hover,
QPushButton#DeclineButtonArt:hover,
QPushButton#AnswerButtonArt:pressed,
QPushButton#DeclineButtonArt:pressed {{
    background: transparent;
    border: none;
    outline: none;
}}

QLabel#PhoneTileArt {{
    background: transparent;
    border: none;
}}

QPushButton#AnswerButton:focus,
QPushButton#DeclineButton:focus,
QPushButton#AnswerButtonArt:focus,
QPushButton#DeclineButtonArt:focus {{ outline: none; }}


/* ============================================================
   ACTIVE CALL TOAST - same panel, in-call controls
   ============================================================ */

QPushButton#CallControl {{
    background-color: rgba(255, 255, 255, 22);
    border: none;
    border-radius: {ts(28)}px;
}}

QPushButton#CallControl:disabled {{
    background-color: rgba(255, 255, 255, 14);
}}


/* ============================================================
   APP NOTIFICATION TOAST
   ============================================================ */

QLabel#NotificationAppIcon {{
    background-color: #FFFFFF;
    border: none;
    border-radius: {ts(18)}px;
}}

/* App Store artwork carries its own colour and rounded corners, so the
   white tile behind it must not show through them */
QLabel#NotificationAppArt {{
    background: transparent;
    border: none;
}}

QLabel#NotificationApp {{
    background: transparent; border: none;
    color: #9EA4AE;
    font-family: "SF Pro Text", "SF Pro Display", "Segoe UI";
    font-size: {tt(18)}px;
    font-weight: 400;
}}

QLabel#NotificationTime {{
    background: transparent; border: none;
    color: #858B95;
    font-family: "SF Pro Text", "Segoe UI";
    font-size: {tt(15)}px;
    font-weight: 400;
}}

QLabel#NotificationTitle {{
    background: transparent; border: none;
    color: #F5F5F7;
    font-family: "SF Pro Display", "SF Pro Text", "Segoe UI";
    font-size: {tt(28)}px;
    font-weight: 500;
}}

QLabel#NotificationBody {{
    background: transparent; border: none;
    color: #9EA4AE;
    font-family: "SF Pro Text", "SF Pro Display", "Segoe UI";
    font-size: {tt(21)}px;
    font-weight: 400;
}}
"""
