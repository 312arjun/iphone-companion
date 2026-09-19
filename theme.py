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
BG = "#0C1016"
# Matches the app icon's own tile colour, sampled from assets/app_icon.png.
# Anything else leaves a faint edge where the mark's rounded corners meet the
# sidebar, because the two darks differ in hue even at the same lightness.
BG_SIDEBAR = "#0E1823"
# The brand band at the top of the sidebar. One step lighter than the sidebar
# on the same blue axis rather than a new hue, so it separates the app
# identity from the navigation without introducing a second accent colour.
BG_SIDEBAR_HEADER = "#142333"
CARD = "#151A22"
CARD_HOVER = "#1C222C"
CARD_SUNK = "#11161D"
BORDER = "#242B36"
BORDER_SOFT = "#1B212A"

# text
TEXT = "#EAEDF2"
TEXT_DIM = "#8B95A3"
TEXT_FAINT = "#5C6672"

# accents
ACCENT = "#0A84FF"
GREEN = "#30D158"
RED = "#FF453A"
AMBER = "#FFB340"

ACTION_COLOURS = {"positive": GREEN, "negative": RED, "neutral": ACCENT}

# toasts
TOAST_BG = "#1B2028"
TOAST_BORDER = "#2C3340"

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
    /* The resize grip is a bare child of the window, so without this it
       fills its rect with the canvas colour and reads as a patch over
       whatever it happens to sit on. It stays functional when transparent. */
    QSizeGrip#sizeGrip {{ background: transparent; border: none; }}
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

    QPushButton#round {{
        background: {TEXT}; border: none; border-radius: 23px;
    }}
    QPushButton#round:hover {{ background: #FFFFFF; }}

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
