"""
widgets.py - the building blocks of the dashboard.

Everything here uses vicons rather than an icon font, and every measurement
is taken off the reference mock: 16px card radius, 20/18px card padding,
13px labels, 12px dim captions, generous row height.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSizePolicy, QSlider,
                               QVBoxLayout, QWidget)

import theme
import vicons


# --------------------------------------------------------------------------- #
# basics
# --------------------------------------------------------------------------- #

def label(text: str, size: int = 13, weight: int = QFont.Normal,
          colour: str | None = None) -> QLabel:
    widget = QLabel(text)
    font = QFont(theme.FONT_FAMILY, size)
    font.setWeight(weight)
    widget.setFont(font)
    widget.setStyleSheet(f"color: {colour or theme.TEXT}; background: transparent;")
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


class Card(QFrame):
    """Rounded panel with an optional title row."""

    def __init__(self, title: str = "", parent=None):
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
        self.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(icon_label(glyph, 22, glyph_colour), 0, Qt.AlignVCenter)
        column = QVBoxLayout()
        column.setSpacing(0)
        self.value = label(value, 13, QFont.DemiBold)
        self.caption = label(caption, 11, QFont.Normal, theme.TEXT_DIM)
        column.addWidget(self.value)
        column.addWidget(self.caption)
        row.addLayout(column)
        row.addStretch(1)

    def set_value(self, text: str) -> None:
        self.value.setText(text or "\u2014")


# --------------------------------------------------------------------------- #
# phone mockup
# --------------------------------------------------------------------------- #

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

class FeedRow(QFrame):
    """
    One notification: app name, then sender, then body, with the age on the
    right. The earlier single-line variant crammed sender and body together,
    which read as one run-on string.
    """

    def __init__(self, item, pixmap=None, parent=None):
        super().__init__(parent)
        self.item = item
        self.setFixedHeight(68)
        self.setStyleSheet(
            "QFrame { background: transparent; border-radius: 12px; }"
            f"QFrame:hover {{ background: {theme.CARD_HOVER}; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(13)

        art = Artwork(40, 0.28)
        art.set_art(pixmap, "bell", item.app or "?", theme.CARD_HOVER)
        row.addWidget(art, 0, Qt.AlignVCenter)

        column = QVBoxLayout()
        column.setSpacing(1)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(label(item.app or "iPhone", 12, QFont.DemiBold))
        if item.title:
            column.addWidget(label(_clip(item.title, 46), 11, QFont.DemiBold,
                                   theme.TEXT))
        if item.body:
            column.addWidget(label(_clip(item.body, 58), 11, QFont.Normal,
                                   theme.TEXT_DIM))
        row.addLayout(column, 1)

        from store import ago
        right = QVBoxLayout()
        right.setSpacing(2)
        right.addWidget(label(ago(item.at), 11, QFont.Normal, theme.TEXT_FAINT),
                        0, Qt.AlignRight)
        right.addStretch(1)
        row.addLayout(right, 0)


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "\u2026"


class Switch(QAbstractButton):
    """iOS-style toggle. QCheckBox cannot draw a sliding knob via stylesheet."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        track = QRectF(0, 0, self.width(), self.height())
        radius = track.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT if self.isChecked() else "#39404C"))
        p.drawRoundedRect(track, radius, radius)

        knob = self.height() - 6
        x = self.width() - knob - 3 if self.isChecked() else 3
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, 3, knob, knob))


class PageHeader(QWidget):
    """Title plus one line of explanation, as every page in the mock has."""

    def __init__(self, title: str, caption: str = "", parent=None):
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(label(title, 22, QFont.DemiBold))
        if caption:
            column.addWidget(label(caption, 12, QFont.Normal, theme.TEXT_DIM))


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
        if caption:
            column.addWidget(label(caption, 11, QFont.Normal, theme.TEXT_DIM))
        row.addLayout(column, 1)
        self.control = control
        if control is not None:
            row.addWidget(control, 0, Qt.AlignVCenter)


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
            button.setStyleSheet(
                f"QPushButton {{ background: {theme.CARD_SUNK};"
                f" border: 1px solid {theme.BORDER_SOFT}; border-radius: 9px;"
                f" color: {theme.TEXT_DIM}; padding: 0 18px; font-size: 12px; }}"
                f"QPushButton:hover {{ background: {theme.CARD_HOVER}; }}"
                f"QPushButton:checked {{ background: {theme.ACCENT};"
                f" color: #FFFFFF; border-color: {theme.ACCENT};"
                f" font-weight: 600; }}"
            )
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
        column.addWidget(label(title, 13, QFont.DemiBold))
        if caption:
            column.addWidget(label(caption, 11, QFont.Normal, theme.TEXT_DIM))
        row.addLayout(column)
        row.addStretch(1)
