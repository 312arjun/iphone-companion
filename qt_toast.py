"""
qt_toast.py - Apple-style toasts, built to the toast QSS spec.

One component, four variants that share the same glass panel and differ only
in content and actions:

    notification    art, app / title / body, age
    missed_call     phone tile, "Missed Call", "from <caller>", Dial
    incoming_call   phone tile, caller, "Incoming Call", Answer + Decline
    active_call     avatar, caller, duration, waveform, in-call controls

All styling is QSS in theme.toast_sheet(). Three things QSS cannot express
are handled here:

  * Rounded corners on a translucent window. QSS cannot round a top-level
    window - the square window edge shows through - so the window stays
    transparent and empty and a child QFrame carries the panel.
  * The soft shadow, via QGraphicsDropShadowEffect on that child frame.
  * The waveform, and the decline handset's 135-degree rotation, which is
    applied to the vector before rasterising so the curve stays smooth.

Entrance is a 280ms OutCubic fade plus a 12px rise; dismissal a 200ms InCubic
fade with an 8px lift. A widget can hold only one QGraphicsEffect and the
frame already has the shadow, so the fade animates the window's opacity
rather than a QGraphicsOpacityEffect - which also keeps the user's banner
opacity preference intact.
"""

from __future__ import annotations

import ctypes
import random
import time

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation,
                            QParallelAnimationGroup, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import (QColor, QFontMetrics, QImage, QPainter,
                           QPainterPath, QPixmap)
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

import calls
import icons
import otp
import theme
import vicons

# Panel metrics, from the 720x150 spec scaled through theme.ts() so the
# widget sizes and the stylesheet's radii can never drift apart. Adjust
# theme.TOAST_SCALE to resize the whole thing.
TOAST_W = theme.ts(720)
TOAST_H = theme.ts(150)
PAD_H = theme.ts(22)
PAD_V = theme.ts(18)
SPACING = theme.ts(18)

ICON_BOX = theme.TOAST_ICON      # as tall as the three lines of text
AVATAR = theme.TOAST_ICON
DIAL_W, DIAL_H = theme.TOAST_DIAL_W, theme.TOAST_DIAL_H
CALL_BTN = theme.ts(64)
CONTROL_BTN = theme.ts(56)
# A code pill never grows past this, however the font measures. Without a
# ceiling a missing font (metrics fall back to a uniform em advance, which
# over-measures badly) would let the pill eat the text column instead of
# just looking a little wide.
COPY_W_MAX = theme.ts(260)

# iOS system colours, used by the drawn tile and call buttons
PHONE_GREEN = "#32D74B"
DECLINE_RED = "#FF3B30"

# Room for the shadow to fall outside the panel. Small while USE_SHADOW is
# off, since it is otherwise just transparent padding around every toast.
USE_SHADOW = False       # see the note in Toast.__init__ before enabling
SHADOW_BLUR = 28
SHADOW_DY = 8
SHADOW_ALPHA = 150
EDGE_X = 10
EDGE_TOP = 8
EDGE_BOTTOM = 16

MARGIN = 14              # gap from the screen edge
GAP = 4                  # between stacked toasts (their shadows add space)

HOLD_MS = 5400
HOLD_CALL_MS = 90_000    # a ringing or active call sticks around
# A code toast waits longer. 5.4s is fine for "you have a message" but it is
# not long enough to notice the banner, move the mouse and click Copy - and
# the one notification you actually need to act on is the worst one to lose.
HOLD_OTP_MS = 20_000
COPIED_MS = 1500         # how long the pill reads "Copied"
RISE_PX = 12
ENTER_MS = 280
LEAVE_MS = 200
LIFT_PX = 8
MAX_VISIBLE = 4

# Active-call controls. Only End Call is real; the rest are disabled because
# the phone offers no way to reach them over BLE:
#   keypad   needs DTMF, which is in-call audio (HFP), not GATT
#   FaceTime needs iAP2 / Continuity
#   mute     is not exposed anywhere, not even in HFP's indicator set
CALL_CONTROLS = (
    ("keypad", "Keypad", "DTMF needs in-call audio, which BLE cannot carry"),
    ("video", "FaceTime", "FaceTime needs iAP2 / Continuity"),
    ("mic_off", "Mute", "iOS does not expose mute state or control"),
    ("dots", "More", "Nothing further is reachable over BLE"),
)

# Labels that do nothing a banner click does not already do.
DISMISS_LABELS = {"clear", "close", "dismiss", "cancel", "ok"}

WAVE_BARS = 30
WAVE_MS = 70
WAVE_LOW = (52, 199, 89)        # green, as on the phone
WAVE_HIGH = (255, 149, 0)       # orange at the peaks


def opacity() -> float:
    """Banner opacity, from Settings > Appearance. Clamped to stay usable."""
    try:
        import prefs
        return max(0.5, min(1.0, float(prefs.get("toast_opacity") or 1.0)))
    except Exception:
        return 1.0


# --------------------------------------------------------------------------- #
# artwork
# --------------------------------------------------------------------------- #

_art_cache: dict[str, QPixmap | None] = {}


def art_for(bundle_id: str, app: str) -> QPixmap | None:
    """
    App artwork at ICON_BOX, rounded, ready for a QLabel.

    QSS border-radius does not clip a QLabel's pixmap, so the rounding is
    baked in. Routed through icons.resolve(), which covers cached App Store
    artwork, drawn tiles for Apple's own apps, and a monogram fallback.
    """
    key = (bundle_id or app or "?").strip()
    if key in _art_cache:
        return _art_cache[key]
    try:
        tile = icons.resolve(bundle_id, app).convert("RGBA")
        image = QImage(tile.tobytes("raw", "RGBA"), tile.width, tile.height,
                       QImage.Format_RGBA8888)
        source = QPixmap.fromImage(image.copy())

        rounded = QPixmap(ICON_BOX, ICON_BOX)
        rounded.fill(Qt.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, ICON_BOX, ICON_BOX),
                            theme.TOAST_ICON_RADIUS, theme.TOAST_ICON_RADIUS)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, ICON_BOX, ICON_BOX, source)
        painter.end()
        pixmap = rounded
    except Exception:
        pixmap = None
    _art_cache[key] = pixmap
    return pixmap


_asset_cache: dict[tuple, QPixmap | None] = {}


def phone_tile(size: int) -> QPixmap:
    """
    The Phone app's mark, drawn rather than loaded.

    assets/box-call-pickup.png works but carries uneven transparent padding,
    which made the tile sit smaller and slightly off-centre next to App Store
    artwork. Drawing it guarantees the green squircle fills the box exactly
    and the handset is centred by measurement, at any scale.
    """
    key = ("tile", size)
    if key in _asset_cache:
        return _asset_cache[key]

    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, True)

    radius = theme.TOAST_ICON_RADIUS
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(PHONE_GREEN))
    p.drawPath(tile)

    glyph = size * 0.50
    p.translate((size - glyph) / 2, (size - glyph) / 2)
    p.setBrush(QColor("#FFFFFF"))
    p.drawPath(vicons.phone_path(glyph))
    p.end()

    _asset_cache[key] = canvas
    return canvas


def call_circle(size: int, decline: bool) -> QPixmap:
    """
    Answer / decline, drawn: a flat circle with a centred handset, rotated
    135 degrees to hang up. Rotating the path rather than a finished pixmap
    keeps the curves smooth and the shape centred.
    """
    key = ("circle", size, decline)
    if key in _asset_cache:
        return _asset_cache[key]

    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(DECLINE_RED if decline else PHONE_GREEN))
    p.drawEllipse(QRectF(0, 0, size, size))

    glyph = size * 0.46
    p.translate((size - glyph) / 2, (size - glyph) / 2)
    if decline:
        p.translate(glyph / 2, glyph / 2)
        p.rotate(135)
        p.translate(-glyph / 2, -glyph / 2)
    p.setBrush(QColor("#FFFFFF"))
    p.drawPath(vicons.phone_path(glyph))
    p.end()

    _asset_cache[key] = canvas
    return canvas


def initials(name: str) -> str:
    parts = [p for p in (name or "").split() if any(c.isalpha() for c in p)]
    if not parts:
        return ""
    return "".join(next(c for c in p if c.isalpha())
                   for p in parts[:2]).upper()


def handset(size: int, decline: bool) -> QPixmap:
    """
    The handset on a transparent square, rotated before rasterising.

    Not used by the toasts any more - call_circle() draws the whole button -
    but kept because it is the only way to get a standalone handset pixmap at
    an arbitrary angle, which the dashboard may want.
    """
    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing, True)
    if decline:
        painter.translate(size / 2, size / 2)
        painter.rotate(135)
        painter.translate(-size / 2, -size / 2)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawPath(vicons.phone_path(size))
    painter.end()
    return canvas


_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080


def _no_activate(widget) -> None:
    """Never steal focus, never appear in Alt-Tab."""
    try:
        hwnd = int(widget.winId())
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, _GWL_EXSTYLE,
                              style | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW)
    except Exception:
        pass


class Waveform(QWidget):
    """
    Decorative. Call audio never reaches the PC - it rides HFP over Bluetooth
    Classic, while everything here comes over BLE GATT. There is no sample
    stream to visualise, so this is a smoothed random walk that runs while the
    call is up: honest movement, not a lie about levels.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(theme.ts(170), theme.ts(38))
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._levels = [0.12] * WAVE_BARS
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)

    def start(self) -> None:
        self._timer.start(WAVE_MS)

    def stop(self) -> None:
        self._timer.stop()

    def _step(self) -> None:
        target = random.random() ** 1.7
        self._levels = self._levels[1:] + [
            self._levels[-1] * 0.45 + target * 0.55]
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        bar = self.width() / (WAVE_BARS * 1.7)
        gap = bar * 0.7
        centre = self.height() / 2
        p.setPen(Qt.NoPen)
        for index, level in enumerate(self._levels):
            height = max(2.0, level * self.height())
            mix = min(1.0, level * 1.4)
            p.setBrush(QColor(
                int(WAVE_LOW[0] + (WAVE_HIGH[0] - WAVE_LOW[0]) * mix),
                int(WAVE_LOW[1] + (WAVE_HIGH[1] - WAVE_LOW[1]) * mix),
                int(WAVE_LOW[2] + (WAVE_HIGH[2] - WAVE_LOW[2]) * mix)))
            p.drawRoundedRect(QRectF(index * (bar + gap), centre - height / 2,
                                     bar, height), bar / 2, bar / 2)


# --------------------------------------------------------------------------- #
# one toast
# --------------------------------------------------------------------------- #

class Toast(QWidget):
    closed = Signal(object)

    def __init__(self, item, manager):
        super().__init__(None)
        self.setObjectName("toastRoot")
        self.item = item
        self.manager = manager
        self.actions = list(item.get("actions") or [])
        self.key = item.get("key")

        self.kind = self._classify()
        self.is_call = self.kind in ("incoming_call", "active_call")
        self._drag_from = None
        self._dragged = False
        self._closing = False
        self._anim = None
        self.wave = None

        # A one-time code in the text, if the message carries one. Resolved
        # here rather than in the builder because _hold_ms() needs it too,
        # and only for plain notifications - a call has no body to scan.
        self.otp = (otp.find_in_item(item) if self.kind == "notification"
                    else None)

        if self.kind == "notification":
            # Drop only the dismiss-equivalent actions: clicking the toast
            # already clears it, so a "Clear" button duplicates that - but a
            # missed call's "Dial" really does dial, so it has to survive.
            self.actions = [a for a in self.actions
                            if a[0].strip().lower() not in DISMISS_LABELS]

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(EDGE_X, EDGE_TOP, EDGE_X, EDGE_BOTTOM)
        self.card = QFrame()
        self.card.setObjectName({
            "missed_call": "MissedCallToast",
            "incoming_call": "IncomingCallToast",
            "active_call": "ActiveCallToast",
        }.get(self.kind, "NotificationToast"))
        shell.addWidget(self.card)

        builder = {
            "missed_call": self._build_missed_call,
            "incoming_call": self._build_incoming_call,
            "active_call": self._build_active_call,
        }.get(self.kind, self._build_notification)
        builder()

        # QGraphicsDropShadowEffect renders its target through an offscreen
        # pixmap, and on a frameless WA_TranslucentBackground window that can
        # come out completely blank - the panel disappears with no error at
        # all. Off by default for that reason; flip USE_SHADOW to try it.
        if USE_SHADOW:
            shadow = QGraphicsDropShadowEffect(self.card)
            shadow.setBlurRadius(SHADOW_BLUR)
            shadow.setOffset(0, SHADOW_DY)
            shadow.setColor(QColor(0, 0, 0, SHADOW_ALPHA))
            self.card.setGraphicsEffect(shadow)

        self.setFixedWidth(TOAST_W + EDGE_X * 2)
        self.adjustSize()

        self._life = QTimer(self)
        self._life.setSingleShot(True)
        self._life.timeout.connect(self.dismiss)
        self._life.start(self._hold_ms())

        self._tick = None
        if self.is_call:
            self._tick = QTimer(self)
            self._tick.timeout.connect(self._refresh_call)
            self._tick.start(500)
            self._refresh_call()
        elif item.get("at"):
            self._tick = QTimer(self)
            self._tick.timeout.connect(self._refresh_age)
            self._tick.start(20_000)

    def _classify(self) -> str:
        style = self.item.get("style")
        if style == "active_call":
            return "active_call"
        if style == "call":
            return "incoming_call"
        if (self.item.get("category") or "").lower() == "missed call":
            return "missed_call"
        return "notification"

    def _hold_ms(self) -> int:
        if self.item.get("hold_ms"):
            return self.item["hold_ms"]
        if self.otp:
            return HOLD_OTP_MS
        return HOLD_CALL_MS if self.is_call else HOLD_MS

    # -- pieces ----------------------------------------------------------- #

    def _label(self, name: str, text: str = "") -> QLabel:
        widget = QLabel(text)
        widget.setObjectName(name)
        widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        return widget

    def _phone_tile(self, _name: str) -> QLabel:
        """The Phone app's mark - drawn, so it can never be misaligned."""
        widget = QLabel()
        widget.setObjectName("PhoneTileArt")
        widget.setFixedSize(ICON_BOX, ICON_BOX)
        widget.setAlignment(Qt.AlignCenter)
        widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        widget.setPixmap(phone_tile(ICON_BOX))
        return widget

    def _app_tile(self) -> QLabel:
        """
        Real artwork gets NotificationAppArt (transparent) so the white tile
        behind it cannot show through the pixmap's rounded corners. Only the
        fallback uses NotificationAppIcon and its white background.
        """
        widget = QLabel()
        widget.setFixedSize(ICON_BOX, ICON_BOX)
        widget.setAlignment(Qt.AlignCenter)
        widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        art = art_for(self.item.get("bundle_id", ""), self.item.get("app", ""))
        if art is not None:
            widget.setObjectName("NotificationAppArt")
            widget.setPixmap(art)
        else:
            widget.setObjectName("NotificationAppIcon")
        return widget

    def _avatar(self) -> QLabel:
        widget = QLabel()
        widget.setObjectName("CallerAvatar")
        widget.setFixedSize(AVATAR, AVATAR)
        widget.setAlignment(Qt.AlignCenter)
        widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        letters = initials(self.item.get("title") or "")
        if letters:
            widget.setText(letters)
        else:
            widget.setPixmap(vicons.pixmap("phone", theme.ts(28), "#FFFFFF"))
        return widget

    def _content(self, *rows) -> QWidget:
        holder = QWidget()
        holder.setObjectName("ToastContent")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        for row in rows:
            if isinstance(row, QWidget):
                column.addWidget(row)
            else:
                column.addLayout(row)
        return holder

    def _header(self, app_name: str, app_object: str,
                time_object: str | None) -> QWidget:
        holder = QWidget()
        holder.setObjectName("ToastHeader")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._label(app_object, app_name))
        row.addStretch(1)
        if time_object:
            self.stamp = self._label(time_object, self._age())
            row.addWidget(self.stamp)
        return holder

    def _dial_button(self, index: int, action) -> QPushButton:
        button = QPushButton(action[0])
        button.setObjectName("DialButton")
        button.setFixedSize(DIAL_W, DIAL_H)
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        button.clicked.connect(lambda: self._fire(index))
        return button

    def _call_button(self, index: int, action) -> QPushButton:
        """
        Answer / decline, drawn as a whole button so the circle and the
        handset inside it are always concentric. No QSS background to align
        against, and no hover tint to fight the artwork.
        """
        decline = (action[2] if len(action) > 2 else "") == "negative"
        button = QPushButton()
        button.setObjectName("DeclineButtonArt" if decline
                             else "AnswerButtonArt")
        button.setFixedSize(CALL_BTN, CALL_BTN)
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        button.setToolTip(action[0])
        button.setIcon(call_circle(CALL_BTN, decline))
        button.setIconSize(QSize(CALL_BTN, CALL_BTN))
        button.clicked.connect(lambda: self._fire(index))
        return button

    def _copy_button(self) -> QPushButton:
        """
        The pill for a one-time code.

        Labelled with the code itself rather than the word "Copy", because
        the body is elided to a single line and the digits are usually what
        falls off the end - "LOGIN to your Flipkart account using OTP 1526..."
        loses exactly the part you needed. Putting the code on the button
        makes it readable even when the sentence carrying it is not.

        Styled identically to the missed-call Dial pill - they share every
        QSS selector in theme.toast_sheet(), so the two can never drift. Only
        the width differs, and only when it has to: a 4 to 6 digit code fits
        inside DIAL_W, so in the common case the pill is exactly Dial-sized.
        An 8-digit code needs a little more, hence the measurement.
        """
        button = QPushButton(self.otp)
        button.setObjectName("CopyButton")
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        button.setToolTip("Copy code")
        # ensurePolished first - the font comes from the QSS, so it is not
        # known until Qt has applied the stylesheet. Same trap as _fitted.
        button.ensurePolished()
        metrics = QFontMetrics(button.font())
        # "Copied" replaces the digits on click, so size for whichever is
        # wider or the confirmation would be clipped.
        widest = max(metrics.horizontalAdvance(self.otp),
                     metrics.horizontalAdvance("Copied"))
        self._copy_w = min(COPY_W_MAX, max(DIAL_W, widest + theme.ts(48)))
        button.setFixedSize(self._copy_w, DIAL_H)
        button.clicked.connect(lambda: self._copy(button))
        return button

    def _copy(self, button: QPushButton) -> None:
        """
        Copy the code, confirm in place, and keep the banner up.

        Deliberately does not dismiss. A code is pasted into a field that is
        already waiting, and if the toast vanishes on click you cannot tell
        whether the copy landed or the banner just timed out. Re-arming the
        hold instead leaves time to read "Copied" and to click again.
        """
        QApplication.clipboard().setText(self.otp)
        button.setText("Copied")
        # Parented to self, so it cannot outlive the toast and poke a
        # deleted button.
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(lambda: button.setText(self.otp))
        self._copy_timer.start(COPIED_MS)
        self._arm()

    def _main_row(self) -> QHBoxLayout:
        row = QHBoxLayout(self.card)
        row.setContentsMargins(PAD_H, PAD_V, PAD_H, PAD_V)
        row.setSpacing(SPACING)
        return row

    # -- variants --------------------------------------------------------- #

    def _fitted(self, name: str, text: str, reserve: int) -> QLabel:
        """
        A single-line label, elided to fit.

        Word wrap made the panel grow by a line or two, so a "Call ended"
        toast ended up taller than the missed-call toast beside it. Every
        variant is a fixed height now and long text is cut with an ellipsis,
        which is what the reference does too.

        ensurePolished() is what makes the measurement right - the font comes
        from the stylesheet, not from setFont, so it is not known until Qt has
        applied the QSS.
        """
        widget = self._label(name, "")
        widget.ensurePolished()
        available = max(40, TOAST_W - PAD_H * 2 - ICON_BOX - SPACING - reserve)
        metrics = QFontMetrics(widget.font())
        widget.setText(metrics.elidedText(text or "", Qt.ElideRight,
                                          available))
        return widget

    def _side_column(self, time_object: str, action=None) -> QVBoxLayout:
        """
        Timestamp at the card's right edge with the action beneath it.

        The timestamp used to live inside the text column, which ends where
        the button begins - so it sat well left of the card edge and looked
        misaligned against the button below it.
        """
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        self.stamp = self._label(time_object, self._age())
        self.stamp.setAlignment(Qt.AlignRight | Qt.AlignTop)
        column.addWidget(self.stamp, 0, Qt.AlignRight | Qt.AlignTop)
        column.addStretch(1)
        if action is not None:
            column.addWidget(action, 0, Qt.AlignRight)
            column.addStretch(1)
        return column

    def _build_missed_call(self) -> None:
        self.card.setFixedHeight(TOAST_H)
        row = self._main_row()
        row.addWidget(self._phone_tile("MissedCallIcon"), 0, Qt.AlignVCenter)

        action = (self._dial_button(0, self.actions[0]) if self.actions
                  else None)
        reserve = (DIAL_W if action else theme.ts(70)) + SPACING
        title = self.item.get("title") or "Missed Call"
        caller = self.item.get("body") or ""
        row.addWidget(self._content(
            self._header(self.item.get("app") or "Phone",
                         "MissedCallApp", None),
            self._fitted("MissedCallTitle", title, reserve),
            self._fitted("MissedCallCaller", caller, reserve)), 1)
        row.addLayout(self._side_column("MissedCallTime", action), 0)

    def _build_incoming_call(self) -> None:
        self.card.setFixedHeight(TOAST_H)
        row = self._main_row()
        row.addWidget(self._phone_tile("IncomingCallIcon"), 0, Qt.AlignVCenter)

        self.call_name = self._label(
            "IncomingCaller",
            self.item.get("title") or self.item.get("app") or "")
        self.call_status = self._label("IncomingStatus", "Incoming Call")
        row.addWidget(self._content(
            self._header(self.item.get("app") or "Phone",
                         "IncomingCallApp", None),
            self.call_name, self.call_status), 1)

        for index, action in enumerate(self._ordered_actions()):
            row.addWidget(self._call_button(index, action), 0, Qt.AlignVCenter)

    def _build_active_call(self) -> None:
        column = QVBoxLayout(self.card)
        column.setContentsMargins(PAD_H, PAD_V, PAD_H, PAD_V)
        column.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(SPACING)
        top.addWidget(self._avatar(), 0, Qt.AlignVCenter)
        self.call_name = self._label(
            "IncomingCaller",
            self.item.get("title") or self.item.get("app") or "")
        self.call_status = self._label("IncomingStatus", "from your iPhone")
        top.addWidget(self._content(self.call_name, self.call_status), 1)

        self.wave = Waveform()
        top.addWidget(self.wave, 0, Qt.AlignVCenter)
        column.addLayout(top)

        controls = QHBoxLayout()
        controls.setSpacing(SPACING)
        for glyph, name, reason in CALL_CONTROLS:
            button = QPushButton()
            button.setObjectName("CallControl")
            button.setFixedSize(CONTROL_BTN, CONTROL_BTN)
            button.setIcon(vicons.icon(glyph, theme.ts(26), theme.TEXT_FAINT))
            button.setIconSize(QSize(theme.ts(26), theme.ts(26)))
            button.setEnabled(False)
            button.setToolTip(f"{name} - {reason}")
            controls.addWidget(button)
        controls.addStretch(1)
        for index, action in enumerate(self.actions):
            controls.addWidget(self._call_button(index, action))
        column.addLayout(controls)

        self.wave.start()

    def _build_notification(self) -> None:
        self.card.setFixedHeight(TOAST_H)
        row = self._main_row()
        row.addWidget(self._app_tile(), 0, Qt.AlignVCenter)

        app = self.item.get("app") or "iPhone"
        title = self.item.get("title") or ""
        body = self.item.get("body") or ""
        if title == app:
            title, body = body, ""

        # The code pill takes the action slot when the message carries a
        # code. An SMS rarely advertises an ANCS action at all, and when it
        # does the action only opens Messages on the phone - strictly less
        # useful than putting the code on the clipboard.
        if self.otp:
            action = self._copy_button()
            reserve = self._copy_w + SPACING
        elif self.actions:
            action = self._dial_button(0, self.actions[0])
            reserve = DIAL_W + SPACING
        else:
            action = None
            reserve = theme.ts(70) + SPACING

        rows = [self._header(app, "NotificationApp", None)]
        if title:
            rows.append(self._fitted("NotificationTitle", title, reserve))
        if body:
            rows.append(self._fitted("NotificationBody", body, reserve))
        row.addWidget(self._content(*rows), 1)

        row.addLayout(self._side_column("NotificationTime", action), 0)

    def _ordered_actions(self):
        """Answer left, decline right - the order the reference shows."""
        return sorted(self.actions,
                      key=lambda a: 1 if (len(a) > 2 and a[2] == "negative")
                      else 0)

    # -- live text -------------------------------------------------------- #

    def _age(self) -> str:
        at = self.item.get("at")
        if not at:
            return "now"
        delta = max(0, int(time.time() - at))
        if delta < 60:
            return "now"
        if delta < 3600:
            return f"{delta // 60}m"
        return f"{delta // 3600}h"

    def _refresh_age(self) -> None:
        if hasattr(self, "stamp"):
            self.stamp.setText(self._age())

    def _refresh_call(self) -> None:
        snap = calls.TRACKER.snapshot()
        if snap.get("state") == "active":
            self.call_status.setText(
                f"from your iPhone \u00b7 {snap.get('duration_text', '')}")
        elif snap.get("state") == "ringing":
            self.call_status.setText("Incoming Call")

    def _fire(self, index: int) -> None:
        actions = (self._ordered_actions() if self.kind == "incoming_call"
                   else self.actions)
        if index >= len(actions):
            return
        callback = actions[index][1] if len(actions[index]) > 1 else None
        self.dismiss()
        if callback:
            try:
                callback()
            except Exception:
                pass

    # -- input ------------------------------------------------------------ #
    #
    # Buttons handle their own clicks, so this only covers the panel itself:
    # drag a call toast, click a notification to dismiss it, hover to hold.

    def enterEvent(self, _event):
        self._life.stop()

    def leaveEvent(self, _event):
        self._arm()

    def mousePressEvent(self, event):
        if self.is_call:
            self._drag_from = event.globalPosition().toPoint()
            self._origin = self.pos()
            self._dragged = False
            self.manager.detach(self)          # stop the stack moving it
            self._life.stop()
            self.setCursor(Qt.SizeAllCursor)

    def mouseMoveEvent(self, event):
        if self._drag_from is None:
            return
        delta = event.globalPosition().toPoint() - self._drag_from
        if delta.manhattanLength() > 3:
            self._dragged = True
            self.move(self._origin + delta)

    def mouseReleaseEvent(self, _event):
        if self._drag_from is not None:
            self._drag_from = None
            self.setCursor(Qt.ArrowCursor)
            if not self._dragged:
                self.dismiss()
            return
        if not self.is_call:
            self.dismiss()

    # -- animation -------------------------------------------------------- #

    def appear(self, target: QPoint) -> None:
        """
        Fade in over 280ms while rising 12px. OutCubic, per the spec.

        The window starts at zero opacity, so if the animation ever fails to
        advance the toast would stay invisible with no error. A one-shot timer
        forces the final value shortly after the animation should have ended -
        worst case it pops into view instead of fading.
        """
        self.move(QPoint(target.x(), target.y() + RISE_PX))
        self.setWindowOpacity(0.0)
        self.show()
        _no_activate(self)

        rise = QPropertyAnimation(self, b"pos", self)
        rise.setDuration(ENTER_MS)
        rise.setEasingCurve(QEasingCurve.OutCubic)
        rise.setEndValue(target)

        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(ENTER_MS)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        fade.setStartValue(0.0)
        fade.setEndValue(opacity())

        self._anim = QParallelAnimationGroup(self)
        self._anim.addAnimation(rise)
        self._anim.addAnimation(fade)
        self._anim.start()
        QTimer.singleShot(ENTER_MS + 120, self._settle)

    def _settle(self) -> None:
        if not self._closing and self.windowOpacity() < opacity() - 0.01:
            self.setWindowOpacity(opacity())

    def animate_to(self, target: QPoint, duration: int = ENTER_MS) -> None:
        """Reflow when a toast above this one leaves."""
        if self._closing:
            return
        if self._anim is not None:
            self._anim.stop()
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.setEndValue(target)
        self._anim.start()

    def _arm(self):
        self._life.stop()
        if not self._closing:
            self._life.start(self._hold_ms())

    def dismiss(self):
        """Fade out over 200ms while lifting 8px. InCubic, per the spec."""
        if self._closing:
            return
        self._closing = True
        self._life.stop()
        if self._tick:
            self._tick.stop()
        if self.wave:
            self.wave.stop()
        self.setCursor(Qt.ArrowCursor)

        if self._anim is not None:
            self._anim.stop()

        lift = QPropertyAnimation(self, b"pos", self)
        lift.setDuration(LEAVE_MS)
        lift.setEasingCurve(QEasingCurve.InCubic)
        lift.setEndValue(QPoint(self.x(), self.y() - LIFT_PX))

        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(LEAVE_MS)
        fade.setEasingCurve(QEasingCurve.InCubic)
        fade.setEndValue(0.0)

        self._anim = QParallelAnimationGroup(self)
        self._anim.addAnimation(lift)
        self._anim.addAnimation(fade)
        self._anim.finished.connect(self._finish)
        self._anim.start()

    def _finish(self):
        self.closed.emit(self)
        self.hide()
        self.deleteLater()


# --------------------------------------------------------------------------- #
# stack manager
# --------------------------------------------------------------------------- #

class ToastManager:
    """
    Owns the on-screen stack. Toasts reflow upward when one leaves.

    If a sink is registered (the dashboard, while it is visible) the toast is
    handed to it instead of being shown on the desktop.
    """

    def __init__(self):
        self.toasts: list[Toast] = []
        self.detached: list[Toast] = []
        self.sink = None

    def set_sink(self, sink) -> None:
        self.sink = sink

    def apply_opacity(self) -> None:
        """Live-update toasts already on screen when the setting changes."""
        value = opacity()
        for toast in list(self.toasts) + list(self.detached):
            try:
                if not toast._closing:
                    toast.setWindowOpacity(value)
            except Exception:
                pass

    def show(self, item: dict) -> None:
        if self.sink is not None:
            try:
                self.sink(item)
                return
            except Exception:
                pass

        if len(self.toasts) >= MAX_VISIBLE:
            self.toasts[0].dismiss()

        # Construction reads stylesheets, artwork and layouts, any of which
        # can fail. Without this, an exception inside a Qt slot printed a
        # traceback and the toast simply never appeared.
        try:
            toast = Toast(item, self)
        except Exception as exc:
            import traceback
            from applog import log
            log(f"toast failed: {exc}", "toast")
            log(traceback.format_exc(), "toast", debug=True)
            return

        toast.closed.connect(self._remove)
        self.toasts.append(toast)
        toast.appear(self._slot(len(self.toasts) - 1))
        self._reflow()

    def dismiss_key(self, key) -> None:
        for toast in list(self.toasts) + list(self.detached):
            if toast.key == key:
                toast.dismiss()

    def detach(self, toast) -> None:
        """A dragged call toast stops taking part in the stack layout."""
        if toast in self.toasts:
            self.toasts.remove(toast)
            self.detached.append(toast)
            self._reflow()

    def clear(self) -> None:
        for toast in list(self.toasts) + list(self.detached):
            toast.dismiss()

    # -- internals -------------------------------------------------------- #

    def _slot(self, index: int) -> QPoint:
        """
        Stacked by each toast's own height. Layouts size the panels, so an
        active call is taller than a notification and a fixed pitch would
        overlap them. Widths include the shadow margin, so x is derived from
        the toast rather than a constant.
        """
        screen = QApplication.primaryScreen().availableGeometry()
        y = screen.top() + MARGIN - EDGE_TOP
        for toast in self.toasts[:index]:
            y += toast.height() + GAP
        width = TOAST_W + EDGE_X * 2
        return QPoint(screen.right() - width - MARGIN + EDGE_X, y)

    def _reflow(self) -> None:
        for index, toast in enumerate(self.toasts):
            if not toast._closing:
                toast.animate_to(self._slot(index))

    def _remove(self, toast) -> None:
        if toast in self.toasts:
            self.toasts.remove(toast)
        if toast in self.detached:
            self.detached.remove(toast)
        self._reflow()


MANAGER = ToastManager()
