"""
widgets.py - the building blocks of the dashboard.

Everything here uses vicons rather than an icon font, and every measurement
is taken off the reference mock: 16px card radius, 20/18px card padding,
13px labels, 12px dim captions, generous row height.
"""

from __future__ import annotations

import math
import time
import weakref
import zlib

from PySide6.QtCore import (QEasingCurve, QPointF, QRectF, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSizePolicy, QSlider,
                               QVBoxLayout, QWidget)

import otp
import paths
import theme
import vicons


# --------------------------------------------------------------------------- #
# basics
# --------------------------------------------------------------------------- #

# Roles searched in this order when resolving a literal colour back to its
# name. Order matters because palettes contain duplicate values: LIGHT["TEXT"]
# and DARK["CARD"] are both #0A1A2B, so a plain reverse map resolved ordinary
# body text to the CARD role and turned it near-black in dark mode. Text roles
# are tried first, and the search runs against the palette that is actually
# active, never the two merged together.
_ROLE_ORDER = ("TEXT", "TEXT_DIM", "TEXT_FAINT", "ACCENT", "GREEN", "RED",
               "AMBER", "TOAST_TEXT", "TOAST_TEXT_DIM", "BG", "BG_SIDEBAR",
               "BG_SIDEBAR_HEADER", "CARD", "CARD_HOVER", "CARD_SUNK",
               "BORDER", "BORDER_SOFT", "TOAST_BG", "TOAST_BORDER",
               "SWITCH_OFF")


def _role_for(colour: str | None) -> str:
    """Which palette role a literal colour came from. None means body text."""
    if not colour:
        return "TEXT"
    active = theme.LIGHT if theme.MODE == "light" else theme.DARK
    wanted = colour.upper()
    for role in _ROLE_ORDER:
        if active.get(role, "").upper() == wanted:
            return role
    return "TEXT"

# Every label ever made, weakly held, so a theme switch can restyle them
# without keeping dead widgets alive.
_LABELS: list = []

_WEIGHT_CSS = {
    QFont.Thin: 100, QFont.Light: 300, QFont.Normal: 400,
    QFont.Medium: 500, QFont.DemiBold: 600, QFont.Bold: 700,
    QFont.ExtraBold: 800, QFont.Black: 900,
}


def _style_label(widget: QLabel) -> None:
    """
    Apply size, weight and colour through the stylesheet.

    All three go in the stylesheet on purpose. Setting any stylesheet on a
    widget makes Qt resolve its font from QSS, where the global
    `QWidget { font-size: 13px }` rule then beats QWidget.setFont() - which
    silently pinned every label in the app to 13px no matter what size was
    asked for. Putting font-size in the same rule wins.
    """
    role = getattr(widget, "_role", None)
    colour = getattr(theme, role, theme.TEXT) if role else theme.TEXT
    widget.setStyleSheet(
        "color: %s; background: transparent; font-family: \"%s\";"
        " font-size: %dpx; font-weight: %d;"
        % (colour, theme.FONT_FAMILY, getattr(widget, "_size", 13),
           _WEIGHT_CSS.get(getattr(widget, "_weight", QFont.Normal), 400)))


def restyle_labels() -> None:
    """Re-colour every live label after a palette change. Dead references
    are dropped as they are found, which keeps the list from growing."""
    alive = []
    for ref in _LABELS:
        widget = ref()
        if widget is None:
            continue
        alive.append(ref)
        try:
            _style_label(widget)
        except RuntimeError:        # underlying C++ object already deleted
            pass
    _LABELS[:] = alive


def label(text: str, size: int = 13, weight: int = QFont.Normal,
          colour: str | None = None) -> QLabel:
    widget = QLabel(text)
    widget._size = size
    widget._weight = weight
    # Stored as a role name, not a literal, so the colour follows the theme.
    widget._role = _role_for(colour)
    _style_label(widget)
    _LABELS.append(weakref.ref(widget))
    return widget


def icon_label(name: str, size: int = 20, colour: str | None = None) -> QLabel:
    widget = QLabel()
    widget.setPixmap(vicons.pixmap(name, size, colour or theme.TEXT_DIM))
    widget.setFixedSize(size, size)
    widget.setStyleSheet("background: transparent;")
    return widget


def ghost_button(name: str, size: int = 22, colour: str | None = None,
                 box: int = 40) -> QPushButton:
    button = QPushButton()
    button.setObjectName("ghost")
    button.setIcon(vicons.icon(name, size, colour or theme.TEXT_DIM))
    button.setIconSize(vicons.pixmap(name, size).size())
    button.setFixedSize(box, box)
    button.setCursor(Qt.PointingHandCursor)
    return button



_IMAGE_LABELS: list = []


def _tinted(name: str, size: int, colour: str) -> QPixmap:
    """
    A bundled PNG recoloured to a flat tint, using its own alpha as a mask.

    The supplied artwork is a mix: some pieces are dark line art, some are
    filled brand colours. Left as-is, the dark ones vanish against a dark
    card. Tinting every one of them to a single colour fixes the visibility
    and makes the set consistent with the vector icons beside them - the
    cost is the brand colours, which is the right trade for a 16px glyph
    that has to be legible in both themes.
    """
    source = QPixmap(paths.bundled("assets", name + ".png"))
    if source.isNull():
        return source
    scaled = source.scaled(size, size, Qt.KeepAspectRatio,
                           Qt.SmoothTransformation)
    tinted = QPixmap(scaled.size())
    tinted.fill(Qt.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, scaled)
    # SourceIn keeps the destination's alpha and takes the source's colour,
    # which is what turns the artwork into a flat silhouette.
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(colour))
    painter.end()
    return tinted


def _style_image(widget: QLabel) -> None:
    size = getattr(widget, "_size", 16)
    name = getattr(widget, "_name", "")
    if name:
        widget.setPixmap(_tinted(name, size, theme.TEXT))


def restyle_images() -> None:
    """Re-tint the bundled icons after a palette change."""
    alive = []
    for ref in _IMAGE_LABELS:
        widget = ref()
        if widget is None:
            continue
        alive.append(ref)
        try:
            _style_image(widget)
        except RuntimeError:
            pass
    _IMAGE_LABELS[:] = alive


def image_label(name: str, size: int = 16) -> QLabel:
    """
    A bundled PNG as a label, for the card-header icons.

    Separate from icon_label, which draws vector glyphs. These are supplied
    artwork used at their native 16px rather than upscaled, and tinted to
    theme.TEXT so they read in both palettes - see _tinted().

    A missing file yields an empty label rather than raising, so a bad name
    costs an icon and not the window.
    """
    widget = QLabel()
    widget.setObjectName("imageIcon")
    widget.setFixedSize(size, size)
    widget._name = name
    widget._size = size
    _style_image(widget)
    _IMAGE_LABELS.append(weakref.ref(widget))
    return widget

class Card(QFrame):
    """
    Rounded panel with an optional title row.

    A title may carry a small coloured glyph, as the mockups have it. Kept
    optional rather than mandatory: an icon earns its place when it helps
    identify the card at a glance in a grid of them, and costs clarity when
    it merely decorates a heading that was already unambiguous.
    """

    def __init__(self, title: str = "", glyph: str = "",
                 glyph_colour: str | None = None, image: str = "",
                 bar: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 18)
        self.body.setSpacing(14)
        self.header = None
        if title:
            self.header = QHBoxLayout()
            self.header.setContentsMargins(0, 0, 0, 0)
            self.header.setSpacing(8)
            if bar:
                # The Media page heads its sections with a short accent rule
                # instead of an icon, which is what the mockup shows there.
                rule = QFrame()
                rule.setObjectName("titleBar")
                rule.setFixedSize(3, 17)
                self.header.addWidget(rule, 0, Qt.AlignVCenter)
            if image:
                # Supplied artwork wins over a vector glyph when both are
                # given, since it is the more specific request.
                self.header.addWidget(image_label(image, 17), 0,
                                      Qt.AlignVCenter)
            elif glyph:
                self.header.addWidget(
                    icon_label(glyph, 16, glyph_colour or theme.ACCENT), 0,
                    Qt.AlignVCenter)
            self.title = label(title, 14, QFont.DemiBold)
            self.header.addWidget(self.title)
            self.header.addStretch(1)
            self.body.addLayout(self.header)


class NavButton(QPushButton):
    def __init__(self, text: str, glyph: str, parent=None):
        super().__init__(f"   {text}", parent)
        self.setObjectName("nav")
        self.glyph = glyph
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(48)
        self.setIconSize(vicons.pixmap(glyph, 22).size())
        self._paint(False)
        self.toggled.connect(self._paint)

    def _paint(self, active: bool) -> None:
        self.setIcon(vicons.icon(self.glyph, 22,
                                 theme.TEXT if active else theme.TEXT_DIM))


class TileButton(QPushButton):
    """Quick-control tile: centred icon above a caption, as in the mock."""

    def __init__(self, glyph: str, caption: str, colour: str | None = None,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("tile")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(88)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 14, 8, 12)
        column.setSpacing(10)
        self.glyph_label = icon_label(glyph, 25, colour or theme.TEXT)
        column.addWidget(self.glyph_label, 0, Qt.AlignHCenter)
        column.addWidget(label(caption, 12, QFont.Normal, theme.TEXT),
                         0, Qt.AlignHCenter)

    def set_glyph(self, glyph: str, colour: str | None = None) -> None:
        self.glyph_label.setPixmap(
            vicons.pixmap(glyph, 25, colour or theme.TEXT))


class ShortcutTile(QPushButton):
    """Coloured rounded square with a caption beneath, for the Shortcuts card."""

    def __init__(self, glyph: str, caption: str, colour: str, parent=None):
        super().__init__(parent)
        self.setObjectName("tile")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(104)
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 14, 8, 12)
        column.setSpacing(10)

        chip = QLabel()
        chip.setFixedSize(44, 44)
        canvas = QPixmap(44, 44)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 44, 44), 12, 12)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colour))
        painter.drawPath(path)
        glyph_pixmap = vicons.pixmap(glyph, 24, "#FFFFFF")
        painter.drawPixmap(10, 10, glyph_pixmap)
        painter.end()
        chip.setPixmap(canvas)
        chip.setStyleSheet("background: transparent;")

        column.addWidget(chip, 0, Qt.AlignHCenter)
        column.addWidget(label(caption, 12, QFont.Normal, theme.TEXT),
                         0, Qt.AlignHCenter)


class StatusPill(QFrame):
    """The 'Connected' chip that sits top-right in the mock."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sunk")
        self.setFixedHeight(32)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 14, 0)
        row.setSpacing(9)
        self.dot = QLabel()
        self.dot.setFixedSize(9, 9)
        row.addWidget(self.dot, 0, Qt.AlignVCenter)
        self.text = label("Connecting", 12, QFont.DemiBold)
        row.addWidget(self.text)

    def set_state(self, connected: bool, text: str) -> None:
        colour = theme.GREEN if connected else theme.AMBER
        self.dot.setStyleSheet(f"background: {colour}; border-radius: 4px;")
        self.text.setText(text)


class InfoRow(QFrame):
    """Icon + key on the left, value right-aligned. Used by the info cards."""

    def __init__(self, glyph: str, key: str, value: str = "",
                 glyph_colour: str | None = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.setFixedHeight(38)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(13)
        row.addWidget(icon_label(glyph, 19, glyph_colour), 0, Qt.AlignVCenter)
        row.addWidget(label(key, 12, QFont.Normal, theme.TEXT_DIM), 0,
                      Qt.AlignVCenter)
        row.addStretch(1)
        self.value = label(value, 12, QFont.DemiBold)
        row.addWidget(self.value, 0, Qt.AlignVCenter)

    def set_value(self, text: str) -> None:
        self.value.setText(text or "\u2014")


class StackRow(QFrame):
    """Icon + stacked value/caption, the hero layout from the mock."""

    def __init__(self, glyph: str, value: str, caption: str,
                 glyph_colour: str | None = None, parent=None):
        super().__init__(parent)
        # Transparent by object name, not inline. An inline stylesheet here
        # outranked the #factTile rule on Overview and left those tiles with
        # no surface at all.
        self.setObjectName("stackRow")
        row = QHBoxLayout(self)
        # Padded, because these are used as tiles on Overview where a flush
        # icon against the border looked cramped. A transparent stackRow in
        # a list is unaffected - the padding only shows once there is a
        # surface behind it.
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(12)
        row.addWidget(icon_label(glyph, 22, glyph_colour), 0, Qt.AlignVCenter)
        column = QVBoxLayout()
        column.setSpacing(0)
        self.value = label(value, 13, QFont.DemiBold)
        self.caption = label(caption, 11, QFont.Normal, theme.TEXT_DIM)
        # Stretches above and below keep the two lines together as one block
        # in the middle. Without them a tall tile - which is what these are
        # on Overview now - pins the value to the top and the caption to the
        # bottom with a hole between.
        column.addStretch(1)
        column.addWidget(self.value)
        column.addWidget(self.caption)
        column.addStretch(1)
        row.addLayout(column)
        row.addStretch(1)

    def set_value(self, text: str) -> None:
        self.value.setText(text or "\u2014")


# --------------------------------------------------------------------------- #
# phone mockup
# --------------------------------------------------------------------------- #


class SourceChip(QFrame):
    """
    Which app the audio is coming from, as a small pill.

    AMS reports the player name, so this is real information rather than a
    guess - and it matters, because the transport controls act on whatever
    is playing, not on a particular app. Hidden entirely when nothing is
    playing: an empty pill reading "-" is worse than no pill.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sourceChip")
        self.setFixedHeight(24)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 0, 11, 0)
        row.setSpacing(7)
        self.icon = icon_label("music", 13, theme.ACCENT)
        row.addWidget(self.icon, 0, Qt.AlignVCenter)
        self.name = label("", 11, QFont.DemiBold)
        row.addWidget(self.name, 0, Qt.AlignVCenter)
        self.setVisible(False)

    def set_source(self, player: str) -> None:
        text = (player or "").strip()
        self.name.setText(text)
        self.setVisible(bool(text))

class PhoneMock(QWidget):
    """
    The lock-screen render from the mock. We cannot read the real wallpaper
    over BLE, so this is a painted stand-in: a titanium frame, a blue gradient
    screen with two light sweeps, the lock glyph, the time and the date.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(196, 366)
        self.time_text = "9:41"
        self.date_text = ""

    def set_clock(self, time_text: str, date_text: str) -> None:
        self.time_text, self.date_text = time_text, date_text
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        body = QRectF(2, 2, self.width() - 4, self.height() - 4)
        frame = QLinearGradient(body.topLeft(), body.bottomRight())
        frame.setColorAt(0, QColor("#4A5260"))
        frame.setColorAt(0.5, QColor("#2A313C"))
        frame.setColorAt(1, QColor("#454D5A"))
        p.setPen(Qt.NoPen)
        p.setBrush(frame)
        p.drawRoundedRect(body, 34, 34)

        screen = body.adjusted(5, 5, -5, -5)
        wallpaper = QLinearGradient(screen.topLeft(), screen.bottomRight())
        wallpaper.setColorAt(0, QColor("#0B2B52"))
        wallpaper.setColorAt(0.45, QColor("#123E73"))
        wallpaper.setColorAt(1, QColor("#05101F"))
        p.setBrush(wallpaper)
        p.drawRoundedRect(screen, 30, 30)

        clip = QPainterPath()
        clip.addRoundedRect(screen, 30, 30)
        p.save()
        p.setClipPath(clip)
        for offset, alpha, width in ((0.18, 46, 90), (0.52, 30, 130)):
            sweep = QPainterPath()
            start = screen.top() + screen.height() * offset
            sweep.moveTo(screen.left(), start)
            sweep.cubicTo(screen.left() + screen.width() * 0.45, start - 40,
                          screen.left() + screen.width() * 0.6, start + 70,
                          screen.right(), start + 10)
            pen = QPen(QColor(120, 190, 255, alpha), width)
            pen.setCapStyle(Qt.RoundCap)
            p.strokePath(sweep, pen)
        p.restore()

        # notch
        p.setBrush(QColor("#05080D"))
        p.drawRoundedRect(QRectF(screen.center().x() - 26, screen.top() + 7,
                                 52, 15), 7, 7)

        # lock + clock
        p.drawPixmap(int(screen.center().x() - 8), int(screen.top() + 44),
                     vicons.pixmap("lock", 16, "#DDE7F5"))

        font = QFont(theme.FONT_FAMILY, 29)
        font.setWeight(QFont.Light)
        p.setFont(font)
        p.setPen(QColor("#F2F6FC"))
        p.drawText(QRectF(screen.left(), screen.top() + 58, screen.width(), 44),
                   Qt.AlignHCenter | Qt.AlignVCenter, self.time_text)

        font = QFont(theme.FONT_FAMILY, 8)
        p.setFont(font)
        p.setPen(QColor("#C6D4E6"))
        p.drawText(QRectF(screen.left(), screen.top() + 99, screen.width(), 16),
                   Qt.AlignHCenter | Qt.AlignVCenter, self.date_text)

        # side buttons, which the mock shows on the titanium rail
        p.setBrush(QColor("#5A6272"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(0, body.top() + 82, 2.6, 30), 1.3, 1.3)
        p.drawRoundedRect(QRectF(0, body.top() + 124, 2.6, 30), 1.3, 1.3)
        p.drawRoundedRect(QRectF(body.right() - 0.6, body.top() + 104, 2.6, 46),
                          1.3, 1.3)

        # home indicator
        p.setBrush(QColor(255, 255, 255, 170))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(screen.center().x() - 34, screen.bottom() - 13,
                                 68, 4), 2, 2)


# --------------------------------------------------------------------------- #
# battery + media chrome
# --------------------------------------------------------------------------- #

class BatteryPill(QWidget):
    """The chunky battery indicator from the hero and Battery cards."""

    def __init__(self, width: int = 62, height: int = 30, parent=None):
        super().__init__(parent)
        self.level = 0
        self.setFixedSize(width, height)

    def set_level(self, level: int | None) -> None:
        self.level = 0 if level is None else max(0, min(100, int(level)))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        body = QRectF(0.5, 1.5, self.width() - 8, self.height() - 3)
        radius = body.height() * 0.32

        p.setPen(QPen(QColor(theme.BORDER), 1.8))
        p.setBrush(QColor(theme.CARD_SUNK))
        p.drawRoundedRect(body, radius, radius)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.BORDER))
        p.drawRoundedRect(QRectF(self.width() - 6, self.height() / 2 - 5, 4, 10),
                          2, 2)

        if self.level <= 0:
            return
        inner = body.adjusted(3.5, 3.5, -3.5, -3.5)
        colour = theme.GREEN
        if self.level <= 10:
            colour = theme.RED
        elif self.level <= 20:
            colour = theme.AMBER
        fill = QLinearGradient(inner.topLeft(), inner.bottomLeft())
        fill.setColorAt(0, QColor(colour).lighter(118))
        fill.setColorAt(1, QColor(colour))
        p.setBrush(fill)
        width = max(inner.height(), inner.width() * self.level / 100)
        p.drawRoundedRect(QRectF(inner.left(), inner.top(), width,
                                 inner.height()), radius * 0.7, radius * 0.7)


class Meter(QWidget):
    """Thin capacity / progress track."""

    def __init__(self, height: int = 7, colour: str | None = None, parent=None):
        super().__init__(parent)
        self.fraction = 0.0
        self.colour = colour or theme.GREEN
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_fraction(self, fraction: float) -> None:
        self.fraction = max(0.0, min(1.0, fraction or 0.0))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        radius = self.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.CARD_SUNK))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()),
                          radius, radius)
        if self.fraction <= 0:
            return
        p.setBrush(QColor(self.colour))
        p.drawRoundedRect(
            QRectF(0, 0, max(self.height(), self.width() * self.fraction),
                   self.height()), radius, radius)


class Sparkline(QWidget):
    """
    Battery over this session, as an area chart.

    Drawn as bars against a fixed 0-100 axis this was meaningless: battery
    moves a percent or two in an hour, so every bar was the same height and it
    read as a solid green wall. The y-axis now auto-ranges to the values
    actually seen (with a little padding), so a 2% drop is visible, and it says
    so plainly until there is more than one distinct reading.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples: list[int] = []
        self.setMinimumHeight(96)

    def set_samples(self, samples) -> None:
        self.samples = [max(0, min(100, int(value))) for value in samples]
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setFont(QFont(theme.FONT_FAMILY, 8))

        distinct = sorted(set(self.samples))
        if len(distinct) < 2:
            p.setPen(QColor(theme.TEXT_FAINT))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Collecting battery history\u2026")
            return

        low, high = distinct[0], distinct[-1]
        pad = max(1, (high - low) // 4)
        low, high = max(0, low - pad), min(100, high + pad)
        span = max(1, high - low)

        p.setPen(QColor(theme.TEXT_FAINT))
        for value in (high, (high + low) // 2, low):
            y = 6 + (self.height() - 20) * (high - value) / span
            p.drawText(QRectF(0, y - 7, 32, 14),
                       Qt.AlignLeft | Qt.AlignVCenter, f"{value}%")

        plot = QRectF(38, 6, self.width() - 42, self.height() - 22)
        points = []
        for index, value in enumerate(self.samples):
            x = plot.left() + plot.width() * index / max(1, len(self.samples) - 1)
            y = plot.bottom() - plot.height() * (value - low) / span
            points.append(QPointF(x, y))

        area = QPainterPath()
        area.moveTo(points[0].x(), plot.bottom())
        for point in points:
            area.lineTo(point)
        area.lineTo(points[-1].x(), plot.bottom())
        area.closeSubpath()

        fill = QLinearGradient(plot.topLeft(), plot.bottomLeft())
        start = QColor(theme.GREEN)
        start.setAlpha(110)
        end = QColor(theme.GREEN)
        end.setAlpha(8)
        fill.setColorAt(0, start)
        fill.setColorAt(1, end)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawPath(area)

        line = QPainterPath()
        line.moveTo(points[0])
        for point in points[1:]:
            line.lineTo(point)
        p.strokePath(line, QPen(QColor(theme.GREEN), 2.0, Qt.SolidLine,
                                Qt.RoundCap, Qt.RoundJoin))

        p.setBrush(QColor(theme.GREEN))
        p.drawEllipse(points[-1], 3.4, 3.4)


class Artwork(QLabel):
    """Album / app art with rounded corners, or a tinted placeholder."""

    def __init__(self, size: int = 76, radius_ratio: float = 0.22, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._size = size
        self._radius = size * radius_ratio
        self.setStyleSheet("background: transparent;")
        self.set_art(None)

    def set_art(self, pixmap: QPixmap | None, glyph: str = "music",
                letter: str = "", tint: str | None = None) -> None:
        canvas = QPixmap(self._size, self._size)
        canvas.fill(Qt.transparent)
        p = QPainter(canvas)
        p.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self._size, self._size),
                            self._radius, self._radius)
        p.setClipPath(path)

        if pixmap is not None and not pixmap.isNull():
            p.drawPixmap(0, 0, self._size, self._size, pixmap)
        elif letter:
            p.fillRect(0, 0, self._size, self._size,
                       QColor(tint or theme.CARD_HOVER))
            p.setPen(QColor("#FFFFFF"))
            font = QFont(theme.FONT_FAMILY, int(self._size * 0.36),
                         QFont.DemiBold)
            p.setFont(font)
            p.drawText(canvas.rect(), Qt.AlignCenter, letter[:1].upper())
        else:
            p.fillRect(0, 0, self._size, self._size, QColor(theme.CARD_SUNK))
            size = int(self._size * 0.42)
            p.drawPixmap((self._size - size) // 2, (self._size - size) // 2,
                         vicons.pixmap(glyph, size, theme.TEXT_FAINT))
        p.end()
        self.setPixmap(canvas)


# --------------------------------------------------------------------------- #
# notification row
# --------------------------------------------------------------------------- #


# Hues for the per-app accent bar on notification rows. Picked by hashing the
# bundle id, so an app keeps the same colour across restarts and between
# machines - a random or insertion-order colour would shuffle every launch and
# be useless for recognising an app at a glance. Hues only; saturation and
# lightness come from the theme so the bars sit in the palette rather than
# fighting it.
# The hue comes straight off the hash, across the whole circle, rather than
# indexing a fixed list. Buckets lose to the birthday paradox: ten bundles
# into sixteen hues predicts under eight distinct colours, and icon_cache
# already shows ~40 bundles in real use. Taking hue = hash % 360 makes a
# clash mean two apps landing within a degree of each other, which is rare
# and harmless, instead of sharing a slot outright.


def accent_for(bundle_id: str, app: str = "") -> str:
    """A stable colour for one app, as a hex string."""
    key = (bundle_id or app or "?").encode("utf-8")
    # crc32, not sum(bytes): a byte sum collides constantly on strings of
    # similar length and content, which put Instagram and Messages on the
    # same colour - the one thing the bar exists to prevent.
    hue = zlib.crc32(key) % 360
    colour = QColor()
    # Muted on purpose. The bar is an identifier, not a status - at full
    # saturation a list of six apps reads as six warnings. Saturation stays
    # low and lightness close to the card, so the bars register at the edge
    # of vision rather than competing with the text beside them.
    if theme.MODE == "light":
        colour.setHsl(hue, 70, 165)
    else:
        colour.setHsl(hue, 75, 110)
    return colour.name().upper()


class FeedRow(QFrame):
    """
    One notification: app name, then sender, then body, with the age on the
    right. The earlier single-line variant crammed sender and body together,
    which read as one run-on string.
    """

    BAR_W = 3

    def __init__(self, item, pixmap=None, accent: bool = False, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("feedRow")
        self.setFixedHeight(68)
        # A left accent bar identifying the app, as on the mockup's
        # Notifications page. Off by default: the Overview and Messages
        # cards show a handful of rows where it reads as noise, while a long
        # unbroken list is exactly where it helps.
        self._accent = accent_for(item.bundle_id, item.app) if accent else None
        row = QHBoxLayout(self)
        row.setContentsMargins(8 + (self.BAR_W + 7 if accent else 0), 8, 8, 8)
        row.setSpacing(13)

        art = Artwork(40, 0.28)
        art.set_art(pixmap, "bell", item.app or "?", theme.CARD_HOVER)
        row.addWidget(art, 0, Qt.AlignVCenter)

        column = QVBoxLayout()
        column.setSpacing(1)
        column.setContentsMargins(0, 0, 0, 0)
        # Every line is allowed to shrink. Without this a long body sets a
        # minimum width on the row, which propagates up through the card and
        # squeezed the Calls card out of the Overview row entirely.
        for widget in (label(item.app or "iPhone", 12, QFont.DemiBold),
                       label(_clip(item.title, 46), 11, QFont.DemiBold,
                             theme.TEXT) if item.title else None,
                       label(_clip(item.body, 58), 11, QFont.Normal,
                             theme.TEXT_DIM) if item.body else None):
            if widget is None:
                continue
            widget.setMinimumWidth(0)
            widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            column.addWidget(widget)
        row.addLayout(column, 1)

        from store import ago
        right = QVBoxLayout()
        right.setSpacing(2)
        right.addWidget(label(ago(item.at), 11, QFont.Normal, theme.TEXT_FAINT),
                        0, Qt.AlignRight)

        # Same one-time-code detection the toast uses - otp.find_in_item is
        # pure and accepts a store.Item, so the dashboard reuses it as-is.
        # Worth having here as well as on the banner: the banner is gone in
        # seconds, and this is where you look when you missed it.
        code = otp.find_in_item(item)
        if code:
            copy = QPushButton(code)
            # Deliberately NOT "CopyButton": that name is already claimed in
            # toast_sheet(), which sheet() appends, so the toast's banner-
            # sized rule would win on specificity and paint this flat.
            copy.setObjectName("FeedCopyButton")
            copy.setCursor(Qt.PointingHandCursor)
            copy.setFocusPolicy(Qt.NoFocus)
            copy.setToolTip("Copy code")
            copy.setFixedHeight(24)
            copy.clicked.connect(lambda _c, c=code, b=copy: self._copy(c, b))
            right.addWidget(copy, 0, Qt.AlignRight)
        right.addStretch(1)
        row.addLayout(right, 0)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._accent:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._accent))
        inset = 9
        p.drawRoundedRect(
            QRectF(8, inset, self.BAR_W, self.height() - inset * 2),
            self.BAR_W / 2, self.BAR_W / 2)
        p.end()

    def _copy(self, code: str, button) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(code)
        button.setText("Copied")
        # Parented to self so it cannot fire after the row is rebuilt by the
        # next refresh, which would poke a deleted button.
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(lambda: button.setText(code))
        self._copy_timer.start(1500)


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "\u2026"


class Switch(QAbstractButton):
    """
    iOS-style toggle. QCheckBox cannot draw a sliding knob via stylesheet.

    The knob position and the track colour are both driven by a single 0..1
    value so they move together. Animating the position alone leaves the
    track snapping between colours under a knob that is still travelling,
    which reads as a glitch rather than as a transition.
    """

    KNOB_MS = 180

    @property
    def track_off(self) -> str:
        """Read at paint time, not stored, so a palette switch takes effect
        without rebuilding every Switch in the window."""
        return theme.SWITCH_OFF

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)

        self._knob_t = 1.0 if self.isChecked() else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self.KNOB_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_knob_t)
        self.toggled.connect(self._animate_to)

    def _animate_to(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._knob_t)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _set_knob_t(self, value) -> None:
        self._knob_t = float(value)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        track = QRectF(0, 0, self.width(), self.height())
        radius = track.height() / 2
        t = self._knob_t

        off, on = QColor(self.track_off), QColor(theme.ACCENT)
        blended = QColor(
            round(off.red() + (on.red() - off.red()) * t),
            round(off.green() + (on.green() - off.green()) * t),
            round(off.blue() + (on.blue() - off.blue()) * t),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(blended)
        p.drawRoundedRect(track, radius, radius)

        knob = self.height() - 6
        travel = self.width() - knob - 6
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(3 + travel * t, 3, knob, knob))


class PageHeader(QWidget):
    """
    Title plus one line of explanation, as every page in the mock has.

    The title is deliberately large - 30px against 13px body - because it is
    the only thing telling you which page you are on besides the sidebar
    highlight. At 22px it competed with card titles instead of outranking
    them.
    """

    def __init__(self, title: str, caption: str = "", parent=None):
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        column.addWidget(label(title, 30, QFont.Bold))
        if caption:
            column.addWidget(label(caption, 13, QFont.Normal, theme.TEXT_DIM))


class SectionHeader(QWidget):
    """
    A card's own header: rounded icon tile, title, caption, and room for a
    control on the right.

    Card(title) draws a plain text heading, which the mockups replace with
    this on the bigger cards. Kept separate rather than folded into Card so
    the small cards stay cheap - most of them want a one-word heading and
    nothing else.
    """

    def __init__(self, glyph: str, title: str, caption: str = "",
                 control: QWidget | None = None, glyph_colour: str | None = None,
                 parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 4)
        row.setSpacing(13)

        tile = QFrame()
        tile.setObjectName("sectionIcon")
        tile.setFixedSize(42, 42)
        inner = QHBoxLayout(tile)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(icon_label(glyph, 21, glyph_colour or theme.ACCENT),
                        0, Qt.AlignCenter)
        row.addWidget(tile, 0, Qt.AlignVCenter)

        column = QVBoxLayout()
        column.setSpacing(1)
        column.addWidget(label(title, 17, QFont.DemiBold))
        if caption:
            column.addWidget(label(caption, 11, QFont.Normal, theme.TEXT_DIM))
        row.addLayout(column, 1)
        if control is not None:
            row.addWidget(control, 0, Qt.AlignVCenter)


class SettingRow(QFrame):
    """Icon, label, caption, and a control on the right."""

    def __init__(self, glyph: str, title: str, caption: str = "",
                 control: QWidget | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("sunk")
        self.setMinimumHeight(60)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(14)
        row.addWidget(icon_label(glyph, 18), 0, Qt.AlignVCenter)
        column = QVBoxLayout()
        column.setSpacing(1)
        column.addWidget(label(title, 12, QFont.DemiBold))
        # Always built, even when empty, so set_caption() can fill it in
        # later without rebuilding the layout.
        self._caption = label(caption, 11, QFont.Normal, theme.TEXT_DIM)
        self._caption.setVisible(bool(caption))
        column.addWidget(self._caption)
        row.addLayout(column, 1)
        self.control = control
        if control is not None:
            row.addWidget(control, 0, Qt.AlignVCenter)

    def set_caption(self, text: str) -> None:
        """Re-label the second line, so a row can report what just happened
        instead of showing the same instruction whatever the outcome."""
        self._caption.setText(text)
        self._caption.setVisible(bool(text))


class FilterTabs(QWidget):
    """Segmented pill selector, as on the mock's Calls page."""

    changed = Signal(str)

    def __init__(self, options, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.buttons = []
        for index, text in enumerate(options):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(34)
            # Styled by object name in theme.sheet(), not inline. An inline
            # stylesheet bakes the palette in at construction and survives a
            # theme switch unchanged, which is what left half the dark UI
            # unreadable before.
            button.setObjectName("filterPill")
            button.clicked.connect(lambda _c, t=text: self._pick(t))
            self.buttons.append(button)
            row.addWidget(button)
            if index == 0:
                button.setChecked(True)
        row.addStretch(1)
        self.current = options[0]

    def _pick(self, text: str) -> None:
        self.current = text
        for button in self.buttons:
            button.setChecked(button.text() == text)
        self.changed.emit(text)


class VolumeSlider(QWidget):
    """
    Absolute volume, which AMS alone cannot do - it only has step up / step
    down. The signal carries a target percentage; whoever is listening decides
    whether to set it outright (Spotify) or approximate it with AMS steps.

    After the user moves it, incoming values are ignored for a couple of
    seconds. The phone only reports volume when it changes, and the steps take
    a moment to land, so without that window the once-a-second refresh yanked
    the handle straight back and the control looked broken.
    """

    moved = Signal(int)
    HOLD_SECONDS = 2.5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._held_until = 0.0
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(icon_label("mute", 19), 0, Qt.AlignVCenter)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.setPageStep(6)
        self.slider.sliderReleased.connect(self._commit)
        self.slider.valueChanged.connect(self._preview)
        self.slider.actionTriggered.connect(self._nudged)
        row.addWidget(self.slider, 1)

        row.addWidget(icon_label("volume", 19), 0, Qt.AlignVCenter)
        self.readout = label("\u2014", 11, QFont.DemiBold, theme.TEXT_DIM)
        self.readout.setFixedWidth(40)
        self.readout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.readout, 0)

    def _preview(self, value: int) -> None:
        self.readout.setText(f"{value}%")

    def _commit(self) -> None:
        self._held_until = time.monotonic() + self.HOLD_SECONDS
        self.moved.emit(self.slider.value())

    def _nudged(self, action: int) -> None:
        """Clicks on the groove and keyboard steps never emit sliderReleased."""
        if action == QSlider.SliderMove:
            return
        QTimer.singleShot(0, self._commit)

    def set_value(self, fraction: float | None) -> None:
        if self.slider.isSliderDown() or time.monotonic() < self._held_until:
            return
        if fraction is None:
            self.readout.setText("\u2014")
            return
        value = int(round(max(0.0, min(1.0, fraction)) * 100))
        if value != self.slider.value():
            self.slider.blockSignals(True)
            self.slider.setValue(value)
            self.slider.blockSignals(False)
        self.readout.setText(f"{value}%")


class LyricsView(QWidget):
    """
    A window of lyric lines with the current one highlighted.

    Synced lyrics carry per-line timestamps, so the view scrolls itself by
    picking the active index; unsynced lyrics just show as static text.
    """

    WINDOW = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(6)
        self.lines = []
        for index in range(self.WINDOW):
            line = label("", 13, QFont.Normal, theme.TEXT_FAINT)
            line.setWordWrap(True)
            line.setAlignment(Qt.AlignCenter)
            self.column.addWidget(line)
            self.lines.append(line)
        self._message = ""

    def show_message(self, text: str) -> None:
        if self._message == text:
            return
        self._message = text
        middle = self.WINDOW // 2
        for index, line in enumerate(self.lines):
            line.setText(text if index == middle else "")
            self._style(line, index == middle, dim=True)

    def show_synced(self, synced, elapsed: float) -> None:
        self._message = ""
        from lyrics import current_index
        active = current_index(synced, elapsed)
        middle = self.WINDOW // 2
        for offset, line in enumerate(self.lines):
            position = active - middle + offset
            text = (synced[position][1]
                    if 0 <= position < len(synced) else "")
            line.setText(text)
            self._style(line, offset == middle and active >= 0)

    def show_plain(self, text: str) -> None:
        self._message = ""
        rows = [row for row in (text or "").splitlines() if row.strip()]
        for index, line in enumerate(self.lines):
            line.setText(rows[index] if index < len(rows) else "")
            self._style(line, False)

    def _style(self, line, active: bool, dim: bool = False) -> None:
        font = QFont(theme.FONT_FAMILY, 15 if active else 13)
        font.setWeight(QFont.DemiBold if active else QFont.Normal)
        line.setFont(font)
        colour = (theme.TEXT if active
                  else (theme.TEXT_FAINT if dim else theme.TEXT_DIM))
        line.setStyleSheet(f"color: {colour}; background: transparent;")


class EmptyState(QWidget):
    """Centred icon + message, for the cards with nothing in them yet."""

    def __init__(self, glyph: str, title: str, caption: str = "", parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 10, 0, 10)
        row.setSpacing(14)
        row.addStretch(1)

        chip = QFrame()
        chip.setObjectName("sunk")
        chip.setFixedSize(46, 46)
        chip_layout = QVBoxLayout(chip)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.addWidget(icon_label(glyph, 20, theme.TEXT_DIM), 0,
                              Qt.AlignCenter)
        row.addWidget(chip, 0, Qt.AlignVCenter)

        column = QVBoxLayout()
        column.setSpacing(2)
        self._title = label(title, 13, QFont.DemiBold)
        column.addWidget(self._title)
        # Always built, even when empty, so set_text() can fill it in later
        # without having to rebuild the layout.
        self._caption = label(caption, 11, QFont.Normal, theme.TEXT_DIM)
        self._caption.setVisible(bool(caption))
        column.addWidget(self._caption)
        row.addLayout(column)
        row.addStretch(1)

    def set_text(self, title: str, caption: str = "") -> None:
        """Re-label in place - the same placeholder serves 'nothing yet' and
        'no search matches', which are different messages, not one."""
        self._title.setText(title)
        self._caption.setText(caption)
        self._caption.setVisible(bool(caption))


class InfoTile(QFrame):
    """
    One cell of the Device Info grid: a rounded icon tile, a dim label, and
    the value on the right.

    Distinct from InfoRow rather than a variant of it, because the mockup's
    grid cell has its own surface - a sunk background and a border - while
    InfoRow is a transparent line inside a card. Trying to make one widget
    do both left it with a style flag threaded through every caller.
    """

    def __init__(self, glyph: str, key: str, value: str = "",
                 glyph_colour: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("infoTile")
        self.setMinimumHeight(60)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 14, 10)
        row.setSpacing(12)

        tile = QFrame()
        tile.setObjectName("infoTileIcon")
        tile.setFixedSize(38, 38)
        inner = QHBoxLayout(tile)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(icon_label(glyph, 19, glyph_colour or theme.ACCENT),
                        0, Qt.AlignCenter)
        row.addWidget(tile, 0, Qt.AlignVCenter)

        # A long key ("Notifications this session") otherwise sets a
        # minimum width the grid cannot honour and the column overflows its
        # card. Ignored size policy lets the label shrink, but QLabel does
        # not elide on its own - it just paints past its rect - so the text
        # is re-elided in resizeEvent against whatever width it ends up
        # with. That is font-independent, which matters: the same layout has
        # to survive Segoe UI and any fallback.
        self._key_text = key
        self.key = label(key, 12, QFont.Normal, theme.TEXT_DIM)
        self.key.setMinimumWidth(0)
        self.key.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self.key, 1, Qt.AlignVCenter)
        self.value = label(value, 13, QFont.DemiBold)
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.value, 0, Qt.AlignVCenter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        metrics = QFontMetrics(self.key.font())
        self.key.setText(metrics.elidedText(
            self._key_text, Qt.ElideRight, max(20, self.key.width())))

    def set_value(self, text: str, colour: str | None = None) -> None:
        self.value.setText(text or "\u2014")
        if colour:
            self.value.setStyleSheet("background: transparent; color: %s;"
                                     % colour)


class ActivityRow(QFrame):
    """
    One line of the activity log: timeline node, time, app badge, text.

    The rail and node are painted rather than built from widgets, because a
    continuous line has to run *through* the row and out both edges to meet
    its neighbours - a child widget would be clipped at the row boundary and
    the line would come out dashed. first/last trim the rail so it starts
    and stops at the end nodes instead of dangling.

    A silenced entry is dimmed in place and tagged, never hidden: the log is
    meant to explain what the rules did, and hiding their effects would make
    them invisible in the one view built to show them.
    """

    RAIL_X = 16          # centre of the rail, from the row's left edge
    NODE_R = 4

    def __init__(self, item, pixmap=None, first=False, last=False,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("activityRow")
        self.setFixedHeight(38)
        self._first, self._last = first, last
        self._silenced = getattr(item, "verdict", "show") == "silent"

        body = " ".join((item.body or "").split())
        text = item.title or item.app
        if body:
            text += " \u2014 " + body
        dim = theme.TEXT_FAINT if self._silenced else theme.TEXT_DIM

        row = QHBoxLayout(self)
        row.setContentsMargins(self.RAIL_X + 16, 0, 12, 0)
        row.setSpacing(10)

        stamp = label(time.strftime("%H:%M:%S", time.localtime(item.at)),
                      11, QFont.Normal, theme.TEXT_FAINT)
        stamp.setFixedWidth(62)
        row.addWidget(stamp, 0, Qt.AlignVCenter)

        art = Artwork(22, 0.3)
        art.set_art(pixmap, "bell", item.app or "?", theme.CARD_HOVER)
        row.addWidget(art, 0, Qt.AlignVCenter)

        name = label(_clip(item.app, 13), 11, QFont.DemiBold, dim)
        name.setFixedWidth(90)
        row.addWidget(name, 0, Qt.AlignVCenter)

        if self._silenced:
            tag = QLabel("silenced by rule")
            tag.setObjectName("silencedTag")
            row.addWidget(tag, 0, Qt.AlignVCenter)

        message = label(_clip(text, 110), 11, QFont.Normal, dim)
        message.setMinimumWidth(0)
        message.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(message, 1, Qt.AlignVCenter)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        mid = self.height() / 2

        p.setPen(QPen(QColor(theme.BORDER), 2))
        top = mid if self._first else 0
        bottom = mid if self._last else self.height()
        if bottom > top:
            p.drawLine(self.RAIL_X, int(top), self.RAIL_X, int(bottom))

        colour = theme.TEXT_FAINT if self._silenced else theme.ACCENT
        p.setPen(QPen(QColor(theme.BG), 2))
        p.setBrush(QColor(colour))
        p.drawEllipse(QRectF(self.RAIL_X - self.NODE_R, mid - self.NODE_R,
                             self.NODE_R * 2, self.NODE_R * 2))
        p.end()


class Waveform(QWidget):
    """
    Decorative audio bars for the Calls hero card.

    Explicitly NOT a level meter. AMS and ANCS carry no audio stream, so
    there is nothing real to visualise - this is motion that says "a call is
    running", and it must never be mistaken for microphone input. The shape
    is a fixed pseudo-random profile scrolled sideways, not a reading.

    The timer only runs while active. An idle animation would repaint a
    dozen bars several times a second for the entire time the app is open,
    to say nothing at all.
    """

    BARS = 34
    TICK_MS = 90

    def __init__(self, width: int = 260, height: int = 54, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._phase = 0
        self._active = False
        # A fixed profile, so the shape is stable rather than jittering at
        # random every frame - scrolling a stable shape reads as sound,
        # random heights read as noise.
        self._profile = [0.25 + 0.75 * abs(math.sin(i * 0.7))
                         * abs(math.cos(i * 0.31)) for i in range(self.BARS * 3)]
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._step)

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if active:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _step(self) -> None:
        self._phase = (self._phase + 1) % len(self._profile)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        gap = 3
        bar_w = max(2, (self.width() - gap * (self.BARS - 1)) / self.BARS)
        mid = self.height() / 2
        base = QColor(theme.ACCENT)
        for i in range(self.BARS):
            if self._active:
                amp = self._profile[(self._phase + i) % len(self._profile)]
            else:
                # A flat, faint resting profile - present but clearly still.
                amp = 0.12
            h = max(2.0, amp * (self.height() - 6))
            # Fade toward the trailing edge so the bars do not end abruptly.
            base.setAlpha(int(40 + 150 * amp * (1 - i / (self.BARS * 1.6))))
            p.setBrush(base)
            x = i * (bar_w + gap)
            p.drawRoundedRect(QRectF(x, mid - h / 2, bar_w, h),
                              bar_w / 2, bar_w / 2)
        p.end()


class InfoBanner(QFrame):
    """
    An explanatory banner: icon tile, a sentence, and a quieter second line.

    Not SectionHeader, whose title is a short heading at 17px DemiBold. Here
    the first line is a full sentence that has to wrap, so it is body-sized
    and the icon aligns to the top of the text rather than its centre.

    Used to state a limitation honestly on the page where someone would
    otherwise go looking for the missing feature.
    """

    def __init__(self, glyph: str, text: str, detail: str = "",
                 glyph_colour: str | None = None, decor: str | None = None,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("infoBanner")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 13, 16, 13)
        row.setSpacing(13)

        tile = QFrame()
        tile.setObjectName("sectionIcon")
        tile.setFixedSize(38, 38)
        inner = QHBoxLayout(tile)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(icon_label(glyph, 19, glyph_colour or theme.ACCENT),
                        0, Qt.AlignCenter)
        row.addWidget(tile, 0, Qt.AlignTop)

        column = QVBoxLayout()
        column.setSpacing(3)
        headline = label(text, 12, QFont.Normal, theme.TEXT)
        headline.setWordWrap(True)
        column.addWidget(headline)
        if detail:
            note = label(detail, 11, QFont.Normal, theme.TEXT_DIM)
            note.setWordWrap(True)
            column.addWidget(note)
        row.addLayout(column, 1)
        if decor:
            # DecorArt is defined below this class, so it is resolved at call
            # time rather than import time - fine, since nothing constructs
            # a banner during module import.
            row.addWidget(DecorArt(decor, 210, 74), 0, Qt.AlignVCenter)


class DecorArt(QWidget):
    """
    Faint background illustration for the right edge of a card.

    Purely decorative, and drawn rather than shipped as an image so it
    re-tints with the palette and stays crisp at any DPI - a PNG would need
    one asset per theme and would soften on a scaled display.

    Kept deliberately low-contrast. It fills dead space at the end of a wide
    card; the moment it competes with the text beside it, it has failed.
    Mouse-transparent, so it never swallows a click meant for the card.
    """

    ALPHA_LINE = 38          # outline
    ALPHA_FILL = 14          # interior wash

    def __init__(self, kind: str = "phone", width: int = 190,
                 height: int = 130, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(width, height)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def _pen(self, weight: float = 1.6) -> QPen:
        colour = QColor(theme.ACCENT)
        colour.setAlpha(self.ALPHA_LINE)
        pen = QPen(colour, weight)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    def _brush(self) -> QColor:
        colour = QColor(theme.ACCENT)
        colour.setAlpha(self.ALPHA_FILL)
        return colour

    def _phone(self, p: QPainter, rect: QRectF) -> None:
        radius = rect.width() * 0.16
        p.setPen(self._pen(1.8))
        p.setBrush(self._brush())
        p.drawRoundedRect(rect, radius, radius)
        # Screen inset and notch, which is what makes it read as a phone
        # rather than a rounded rectangle.
        inset = rect.adjusted(rect.width() * 0.07, rect.height() * 0.05,
                              -rect.width() * 0.07, -rect.height() * 0.05)
        p.setBrush(Qt.NoBrush)
        p.setPen(self._pen(1.0))
        p.drawRoundedRect(inset, radius * 0.75, radius * 0.75)
        notch_w = rect.width() * 0.3
        notch = QRectF(rect.center().x() - notch_w / 2,
                       inset.top() + rect.height() * 0.025,
                       notch_w, max(3.0, rect.height() * 0.028))
        p.setBrush(self._brush())
        p.drawRoundedRect(notch, notch.height() / 2, notch.height() / 2)

    def _bubble(self, p: QPainter, rect: QRectF, flip: bool = False) -> None:
        radius = min(14.0, rect.height() * 0.32)
        p.setPen(self._pen(1.4))
        p.setBrush(self._brush())
        p.drawRoundedRect(rect, radius, radius)
        # A short tail, so it reads as speech rather than a plain box.
        tail = QPainterPath()
        base_y = rect.bottom()
        x = rect.left() + rect.width() * (0.82 if flip else 0.18)
        step = rect.width() * 0.07 * (-1 if flip else 1)
        tail.moveTo(x, base_y - 1)
        tail.lineTo(x + step, base_y + rect.height() * 0.16)
        tail.lineTo(x + step * 2.1, base_y - 1)
        tail.closeSubpath()
        p.drawPath(tail)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        if self.kind == "messages":
            # Phone on the right, two bubbles drifting off to the left, as
            # in the mockup.
            self._phone(p, QRectF(w * 0.6, h * 0.1, w * 0.3, h * 0.84))
            self._bubble(p, QRectF(w * 0.06, h * 0.14, w * 0.42, h * 0.3))
            self._bubble(p, QRectF(w * 0.2, h * 0.56, w * 0.34, h * 0.26),
                         flip=True)
        else:
            self._phone(p, QRectF(w * 0.34, h * 0.08, w * 0.42, h * 0.86))
        p.end()


class SaveNotice(QFrame):
    """
    Transient confirmation that a setting was written.

    Settings apply instantly here, with no Save button, which is the right
    behaviour but leaves nothing to tell you it worked. This fills that gap:
    it appears on a write and hides itself a couple of seconds later.

    It reports what actually happened rather than always saying "Saved" -
    prefs.set() returns whether the file was written, and claiming success
    after a failed write would be worse than staying silent, because the
    setting would then silently revert on the next start.

    Shown and hidden rather than faded. A fade needs a graphics effect, and
    those render blank on some surfaces in this app - see the note in
    qt_toast about QGraphicsDropShadowEffect.
    """

    HOLD_MS = 2200

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("saveNotice")
        self.setFixedHeight(30)
        row = QHBoxLayout(self)
        row.setContentsMargins(11, 0, 14, 0)
        row.setSpacing(8)
        self.icon = icon_label("check", 14, theme.GREEN)
        row.addWidget(self.icon, 0, Qt.AlignVCenter)
        self.text = label("Saved", 12, QFont.DemiBold)
        row.addWidget(self.text, 0, Qt.AlignVCenter)

        # Parented, so it cannot fire after the page is gone.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def flash(self, saved: bool = True, message: str = "") -> None:
        if saved:
            self.text.setText(message or "Saved")
            self.icon.setPixmap(vicons.pixmap("check", 14, theme.GREEN))
            self.setProperty("failed", False)
        else:
            self.text.setText(message or "Could not save")
            self.icon.setPixmap(vicons.pixmap("info", 14, theme.RED))
            self.setProperty("failed", True)
        # Re-polish, or the property change does not reach the stylesheet.
        self.style().unpolish(self)
        self.style().polish(self)
        self.show()
        self._timer.start(self.HOLD_MS)
