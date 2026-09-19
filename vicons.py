"""
vicons.py - vector icons, drawn with QPainter.

The first pass at this UI used Segoe MDL2 glyphs and every single one came out
as a tofu box, because Qt could not resolve the family. Icon fonts are a
dependency we cannot verify at runtime, so every icon here is built from
paths instead. Nothing to install, nothing to fall back on, identical on any
Windows build.

All shapes are drawn in a 24x24 space and scaled to the requested size.

    label.setPixmap(vicons.pixmap("battery", 18, theme.GREEN))
    button.setIcon(vicons.icon("play", 20))
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QPainter, QPainterPath, QPen,
                           QPixmap, QTransform)

BOX = 24.0
_cache: dict[tuple, QPixmap] = {}


# --------------------------------------------------------------------------- #
# individual icons - each draws inside a 24x24 box
# --------------------------------------------------------------------------- #

def _home(p, stroke):
    path = QPainterPath()
    path.moveTo(3.5, 10.5)
    path.lineTo(12, 3.5)
    path.lineTo(20.5, 10.5)
    p.strokePath(path, stroke)
    path = QPainterPath()
    path.moveTo(5.5, 9.8)
    path.lineTo(5.5, 20)
    path.lineTo(18.5, 20)
    path.lineTo(18.5, 9.8)
    p.strokePath(path, stroke)
    p.strokePath(_line(9.8, 20, 9.8, 14.5), stroke)
    p.strokePath(_line(14.2, 20, 14.2, 14.5), stroke)
    p.strokePath(_line(9.8, 14.5, 14.2, 14.5), stroke)


def _music(p, stroke):
    p.strokePath(_line(9.5, 17.5, 9.5, 5.5), stroke)
    p.strokePath(_line(19, 15.5, 19, 4), stroke)
    path = QPainterPath()
    path.moveTo(9.5, 5.5)
    path.lineTo(19, 4)
    p.strokePath(path, stroke)
    brush = QColor(stroke.color())
    p.setPen(Qt.NoPen)
    p.setBrush(brush)
    p.drawEllipse(QRectF(5.6, 15.6, 4.0, 3.4))
    p.drawEllipse(QRectF(15.1, 13.6, 4.0, 3.4))


def _bell(p, stroke):
    path = QPainterPath()
    path.moveTo(6.3, 16.2)
    path.lineTo(6.3, 11.4)
    path.cubicTo(6.3, 7.0, 8.9, 5.1, 12, 5.1)
    path.cubicTo(15.1, 5.1, 17.7, 7.0, 17.7, 11.4)
    path.lineTo(17.7, 16.2)
    p.strokePath(path, stroke)
    p.strokePath(_line(4.5, 16.2, 19.5, 16.2), stroke)
    clapper = QPainterPath()
    clapper.moveTo(10.1, 18.4)
    clapper.cubicTo(10.5, 20.5, 13.5, 20.5, 13.9, 18.4)
    p.strokePath(clapper, stroke)
    p.strokePath(_line(12, 3.2, 12, 5.1), stroke)


def _phone(p, stroke):
    """
    A proper handset silhouette. A rotated arc was not it - that read as a
    hook. This is the standard receiver shape: two pads joined by a curved
    body, drawn filled.
    """
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    path = QPainterPath()
    path.moveTo(6.6, 10.8)
    path.cubicTo(8.04, 13.63, 10.36, 15.94, 13.19, 17.39)
    path.lineTo(15.39, 15.19)
    path.cubicTo(15.66, 14.92, 16.06, 14.83, 16.41, 14.95)
    path.cubicTo(17.53, 15.32, 18.74, 15.52, 19.98, 15.52)
    path.cubicTo(20.53, 15.52, 20.98, 15.97, 20.98, 16.52)
    path.lineTo(20.98, 20.0)
    path.cubicTo(20.98, 20.55, 20.53, 21.0, 19.98, 21.0)
    path.cubicTo(10.59, 21.0, 2.98, 13.39, 2.98, 4.0)
    path.cubicTo(2.98, 3.45, 3.43, 3.0, 3.98, 3.0)
    path.lineTo(7.48, 3.0)
    path.cubicTo(8.03, 3.0, 8.48, 3.45, 8.48, 4.0)
    path.cubicTo(8.48, 5.25, 8.68, 6.45, 9.05, 7.57)
    path.cubicTo(9.16, 7.92, 9.08, 8.31, 8.8, 8.59)
    path.closeSubpath()
    p.drawPath(path)


def _phone_missed(p, stroke):
    _phone(p, stroke)
    pen = QPen(QColor(stroke.color()), 1.8, Qt.SolidLine, Qt.RoundCap)
    p.strokePath(_line(15.2, 3.4, 21.2, 9.4), pen)
    p.strokePath(_line(21.2, 3.4, 15.2, 9.4), pen)


def _chat(p, stroke):
    path = QPainterPath()
    path.addRoundedRect(QRectF(3.5, 4.5, 17, 12.5), 4, 4)
    p.strokePath(path, stroke)
    path = QPainterPath()
    path.moveTo(8, 17)
    path.lineTo(8, 20.5)
    path.lineTo(12.4, 17)
    p.strokePath(path, stroke)


def _device(p, stroke):
    path = QPainterPath()
    path.addRoundedRect(QRectF(7, 2.5, 10, 19), 2.6, 2.6)
    p.strokePath(path, stroke)
    p.strokePath(_line(10.6, 19.2, 13.4, 19.2), stroke)


def _settings(p, stroke):
    """
    A filled cog with a hole punched through it.

    Drawn as outlines - a thin ring plus eight thin teeth - this read as a
    sunburst at 19px, which is the size the sidebar actually uses. A filled
    silhouette built by uniting the teeth with the body and subtracting the
    centre holds its shape at any size.
    """
    body = QPainterPath()
    body.addEllipse(QRectF(4.2, 4.2, 15.6, 15.6))
    for index in range(8):
        tooth = QPainterPath()
        tooth.addRoundedRect(QRectF(10.55, 1.5, 2.9, 5.6), 1.3, 1.3)
        spin = QTransform().translate(12, 12).rotate(index * 45).translate(
            -12, -12)
        body = body.united(spin.map(tooth))

    hole = QPainterPath()
    hole.addEllipse(QRectF(8.5, 8.5, 7.0, 7.0))

    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    p.drawPath(body.subtracted(hole))


def _play(p, stroke):
    path = QPainterPath()
    path.moveTo(7.5, 4.6)
    path.lineTo(19.5, 12)
    path.lineTo(7.5, 19.4)
    path.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    p.drawPath(path)


def _pause(p, stroke):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    p.drawRoundedRect(QRectF(7, 4.8, 3.6, 14.4), 1.4, 1.4)
    p.drawRoundedRect(QRectF(13.4, 4.8, 3.6, 14.4), 1.4, 1.4)


def _next(p, stroke):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    path = QPainterPath()
    path.moveTo(5.5, 5.2)
    path.lineTo(15.5, 12)
    path.lineTo(5.5, 18.8)
    path.closeSubpath()
    p.drawPath(path)
    p.drawRoundedRect(QRectF(16.4, 5.2, 2.8, 13.6), 1.2, 1.2)


def _previous(p, stroke):
    p.save()
    p.translate(24, 0)
    p.scale(-1, 1)
    _next(p, stroke)
    p.restore()


def _volume(p, stroke):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    path = QPainterPath()
    path.moveTo(4, 9.5)
    path.lineTo(7.5, 9.5)
    path.lineTo(12, 5)
    path.lineTo(12, 19)
    path.lineTo(7.5, 14.5)
    path.lineTo(4, 14.5)
    path.closeSubpath()
    p.drawPath(path)
    for radius, span in ((3.4, 0), (6.2, 0)):
        arc = QPainterPath()
        arc.arcMoveTo(QRectF(12 - radius + 2.6, 12 - radius, radius * 2,
                             radius * 2), 60)
        arc.arcTo(QRectF(12 - radius + 2.6, 12 - radius, radius * 2,
                         radius * 2), 60, -120)
        p.strokePath(arc, stroke)


def _mute(p, stroke):
    _volume_body(p, stroke)
    p.strokePath(_line(16.5, 9.5, 21, 14.5), stroke)
    p.strokePath(_line(21, 9.5, 16.5, 14.5), stroke)


def _volume_body(p, stroke):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    path = QPainterPath()
    path.moveTo(3, 9.5)
    path.lineTo(6.5, 9.5)
    path.lineTo(11, 5)
    path.lineTo(11, 19)
    path.lineTo(6.5, 14.5)
    path.lineTo(3, 14.5)
    path.closeSubpath()
    p.drawPath(path)


def _shuffle(p, stroke):
    p.strokePath(_line(3.5, 6.5, 8, 6.5), stroke)
    path = QPainterPath()
    path.moveTo(8, 6.5)
    path.cubicTo(13, 6.5, 12, 17.5, 16.5, 17.5)
    p.strokePath(path, stroke)
    p.strokePath(_line(3.5, 17.5, 8, 17.5), stroke)
    path = QPainterPath()
    path.moveTo(8, 17.5)
    path.cubicTo(13, 17.5, 12, 6.5, 16.5, 6.5)
    p.strokePath(path, stroke)
    _arrow(p, stroke, 16.5, 6.5)
    _arrow(p, stroke, 16.5, 17.5)


def _repeat(p, stroke):
    """A loop with a chevron at each end - no filled block."""
    top = QPainterPath()
    top.moveTo(8.5, 6.6)
    top.lineTo(15.5, 6.6)
    top.arcTo(QRectF(14.2, 6.6, 5.6, 5.6), 90, -180)
    top.lineTo(15.5, 12.2)
    p.strokePath(top, stroke)

    bottom = QPainterPath()
    bottom.moveTo(15.5, 17.4)
    bottom.lineTo(8.5, 17.4)
    bottom.arcTo(QRectF(4.2, 11.8, 5.6, 5.6), 270, -180)
    bottom.lineTo(8.5, 11.8)
    p.strokePath(bottom, stroke)

    chevron = QPainterPath()
    chevron.moveTo(11.2, 4.2)
    chevron.lineTo(8.5, 6.6)
    chevron.lineTo(11.2, 9.0)
    p.strokePath(chevron, stroke)

    chevron = QPainterPath()
    chevron.moveTo(12.8, 15.0)
    chevron.lineTo(15.5, 17.4)
    chevron.lineTo(12.8, 19.8)
    p.strokePath(chevron, stroke)


def _arrow(p, stroke, x, y):
    path = QPainterPath()
    path.moveTo(x - 3, y - 2.6)
    path.lineTo(x, y)
    path.lineTo(x - 3, y + 2.6)
    p.strokePath(path, stroke)


def _heart(p, stroke):
    path = QPainterPath()
    path.moveTo(12, 19.6)
    path.cubicTo(3.5, 14.2, 4.4, 6.2, 9.2, 6.2)
    path.cubicTo(11.1, 6.2, 12, 8.0, 12, 8.0)
    path.cubicTo(12, 8.0, 12.9, 6.2, 14.8, 6.2)
    path.cubicTo(19.6, 6.2, 20.5, 14.2, 12, 19.6)
    p.strokePath(path, stroke)


def _bluetooth(p, stroke):
    path = QPainterPath()
    path.moveTo(9, 7.5)
    path.lineTo(15.5, 16.5)
    path.lineTo(12, 20)
    path.lineTo(12, 4)
    path.lineTo(15.5, 7.5)
    path.lineTo(9, 16.5)
    p.strokePath(path, stroke)


def _battery(p, stroke):
    path = QPainterPath()
    path.addRoundedRect(QRectF(2.5, 7.5, 16, 9), 2.4, 2.4)
    p.strokePath(path, stroke)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    p.drawRoundedRect(QRectF(19.6, 10.2, 2, 3.6), 0.8, 0.8)
    p.drawRoundedRect(QRectF(4.4, 9.4, 8.4, 5.2), 1.2, 1.2)


def _clock(p, stroke):
    path = QPainterPath()
    path.addEllipse(QRectF(3.5, 3.5, 17, 17))
    p.strokePath(path, stroke)
    p.strokePath(_line(12, 7.8, 12, 12.4), stroke)
    p.strokePath(_line(12, 12.4, 15.6, 14.4), stroke)


def _building(p, stroke):
    path = QPainterPath()
    path.moveTo(4, 20.5)
    path.lineTo(4, 9)
    path.lineTo(11, 9)
    path.lineTo(11, 20.5)
    p.strokePath(path, stroke)
    path = QPainterPath()
    path.moveTo(11, 13)
    path.lineTo(20, 13)
    path.lineTo(20, 20.5)
    p.strokePath(path, stroke)
    p.strokePath(_line(3, 20.5, 21, 20.5), stroke)
    p.strokePath(_line(6.6, 12.2, 8.4, 12.2), stroke)
    p.strokePath(_line(6.6, 16, 8.4, 16), stroke)
    p.strokePath(_line(14.4, 16.4, 16.4, 16.4), stroke)


def _lock(p, stroke):
    path = QPainterPath()
    path.addRoundedRect(QRectF(5, 10.5, 14, 10), 2.6, 2.6)
    p.strokePath(path, stroke)
    path = QPainterPath()
    path.arcMoveTo(QRectF(8, 3.5, 8, 8), 0)
    path.arcTo(QRectF(8, 3.5, 8, 8), 0, 180)
    p.strokePath(path, stroke)
    p.strokePath(_line(8, 7.5, 8, 10.5), stroke)
    p.strokePath(_line(16, 7.5, 16, 10.5), stroke)


def _camera(p, stroke):
    path = QPainterPath()
    path.addRoundedRect(QRectF(2.5, 6.5, 19, 13), 3.2, 3.2)
    p.strokePath(path, stroke)
    path = QPainterPath()
    path.addEllipse(QRectF(9, 9.5, 6, 6))
    p.strokePath(path, stroke)
    p.strokePath(_line(8.5, 6.5, 10.5, 4.2), stroke)
    p.strokePath(_line(15.5, 6.5, 13.5, 4.2), stroke)


def _photos(p, stroke):
    """Five distinct petals around a hub, not an asterisk."""
    p.setPen(Qt.NoPen)
    base = QColor(stroke.color())
    for index in range(5):
        p.save()
        p.translate(12, 12)
        p.rotate(index * 72)
        shade = QColor(base)
        shade.setAlpha(140 + index * 22)
        p.setBrush(shade)
        p.drawEllipse(QRectF(-3.3, -9.4, 6.6, 6.6))
        p.restore()
    p.setBrush(QColor(base))
    p.drawEllipse(QRectF(9.6, 9.6, 4.8, 4.8))


def _chevron(p, stroke):
    path = QPainterPath()
    path.moveTo(9.5, 5.5)
    path.lineTo(16, 12)
    path.lineTo(9.5, 18.5)
    p.strokePath(path, stroke)


def _dots(p, stroke):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    for x in (5.6, 12, 18.4):
        p.drawEllipse(QRectF(x - 1.5, 10.5, 3, 3))


def _minimise(p, stroke):
    p.strokePath(_line(5, 12, 19, 12), stroke)


def _maximise(p, stroke):
    path = QPainterPath()
    path.addRect(QRectF(5.5, 5.5, 13, 13))
    p.strokePath(path, stroke)


def _close(p, stroke):
    p.strokePath(_line(6, 6, 18, 18), stroke)
    p.strokePath(_line(18, 6, 6, 18), stroke)


def _apple(p, stroke):
    """
    Fallback only - see SVG_ICONS. Hand-drawing the Apple mark from cubics
    produced a piece of fruit rather than the logo (no bite, no split base),
    so the real silhouette is rendered from SVG when QtSvg is available.
    """
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    body = QPainterPath()
    body.moveTo(12, 7.4)
    body.cubicTo(10.4, 5.7, 7.1, 6.1, 5.5, 8.6)
    body.cubicTo(3.5, 11.6, 4.6, 16.7, 7.4, 19.5)
    body.cubicTo(8.7, 20.8, 10.3, 20.3, 12, 19.5)
    body.cubicTo(13.7, 20.3, 15.3, 20.8, 16.6, 19.5)
    body.cubicTo(19.4, 16.7, 20.5, 11.6, 18.5, 8.6)
    body.cubicTo(16.9, 6.1, 13.6, 5.7, 12, 7.4)
    body.closeSubpath()
    p.drawPath(body)


def _chevron_down(p, stroke):
    path = QPainterPath()
    path.moveTo(6.5, 9.8)
    path.lineTo(12, 15.2)
    path.lineTo(17.5, 9.8)
    p.strokePath(path, stroke)


def _output(p, stroke):
    path = QPainterPath()
    path.addRoundedRect(QRectF(7.5, 2.8, 9, 18.4), 2.4, 2.4)
    p.strokePath(path, stroke)
    p.strokePath(_line(10.6, 19.0, 13.4, 19.0), stroke)
    p.strokePath(_line(19.4, 8.6, 19.4, 15.4), stroke)
    p.strokePath(_line(4.6, 8.6, 4.6, 15.4), stroke)


def _check(p, stroke):
    path = QPainterPath()
    path.moveTo(5.5, 12.8)
    path.lineTo(10, 17.2)
    path.lineTo(18.5, 7.2)
    p.strokePath(path, stroke)


def _info(p, stroke):
    path = QPainterPath()
    path.addEllipse(QRectF(3.5, 3.5, 17, 17))
    p.strokePath(path, stroke)
    p.strokePath(_line(12, 11, 12, 16.6), stroke)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    p.drawEllipse(QRectF(10.9, 7.2, 2.2, 2.2))


def _signal(p, stroke):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    for index in range(4):
        height = 4 + index * 4
        p.drawRoundedRect(QRectF(4 + index * 4.6, 20 - height, 3.2, height),
                          1, 1)


def _keypad(p, stroke):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    for row in range(3):
        for column in range(3):
            p.drawEllipse(QRectF(5.4 + column * 5.6, 4.6 + row * 5.6,
                                 3.2, 3.2))
    p.drawEllipse(QRectF(11.0, 21.4, 2.0, 2.0))


def _video(p, stroke):
    path = QPainterPath()
    path.addRoundedRect(QRectF(2.5, 7, 12.5, 10), 2.6, 2.6)
    p.strokePath(path, stroke)
    lens = QPainterPath()
    lens.moveTo(16.4, 11.2)
    lens.lineTo(21, 8.2)
    lens.lineTo(21, 15.8)
    lens.lineTo(16.4, 12.8)
    lens.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(stroke.color()))
    p.drawPath(lens)


def _mic_off(p, stroke):
    path = QPainterPath()
    path.addRoundedRect(QRectF(9.4, 3.2, 5.2, 9.6), 2.6, 2.6)
    p.strokePath(path, stroke)
    arc = QPainterPath()
    arc.arcMoveTo(QRectF(6.2, 6.4, 11.6, 11.6), 200)
    arc.arcTo(QRectF(6.2, 6.4, 11.6, 11.6), 200, 140)
    p.strokePath(arc, stroke)
    p.strokePath(_line(12, 18.2, 12, 21), stroke)
    slash = QPen(stroke)
    slash.setWidthF(stroke.widthF() * 1.1)
    p.strokePath(_line(4.6, 3.8, 19.4, 20.2), slash)


def _line(x1, y1, x2, y2) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(x1, y1)
    path.lineTo(x2, y2)
    return path


DRAW = {
    "home": _home, "music": _music, "bell": _bell, "phone": _phone,
    "phone_missed": _phone_missed,
    "chat": _chat, "device": _device, "settings": _settings,
    "play": _play, "pause": _pause, "next": _next, "previous": _previous,
    "volume": _volume, "mute": _mute, "shuffle": _shuffle, "repeat": _repeat,
    "heart": _heart, "bluetooth": _bluetooth, "battery": _battery,
    "clock": _clock, "building": _building, "lock": _lock, "camera": _camera,
    "photos": _photos, "chevron": _chevron, "chevron_down": _chevron_down,
    "dots": _dots, "output": _output, "check": _check, "info": _info,
    "keypad": _keypad, "video": _video, "mic_off": _mic_off,
    "minimise": _minimise, "maximise": _maximise, "close": _close,
    "apple": _apple, "signal": _signal,
}


# --------------------------------------------------------------------------- #
# SVG icons
#
# A few marks are not worth hand-drawing from cubics - the Apple logo needs
# the bite and the split base to be recognisable, and the Spotify mark needs
# three nested arcs. PySide6 ships QtSvg, so these render from real path data
# and fall back to DRAW if the module is missing.
# --------------------------------------------------------------------------- #

SVG_ICONS = {
    # Drawn for a 24px box rather than 384x512. The previous path was built
    # for a much larger viewBox, so at 19px the leaf closed up against the
    # body and the bite disappeared.
    "apple": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path fill="{colour}" d="M12.152 6.896c-.948 0-2.415-1.078-3.96-1.04'
        '-2.04.027-3.91 1.183-4.961 3.014-2.117 3.675-.546 9.103 1.519 12.09'
        '1.013 1.454 2.208 3.09 3.792 3.039 1.52-.065 2.09-.987 3.935-.987'
        '1.831 0 2.35.987 3.96.948 1.637-.026 2.676-1.48 3.676-2.948 1.156'
        '-1.688 1.636-3.325 1.662-3.415-.039-.013-3.182-1.221-3.22-4.857'
        '-.026-3.04 2.48-4.494 2.597-4.559-1.429-2.09-3.623-2.324-4.377'
        '-2.376-2.09-.156-3.844 1.14-4.663 1.14zM15.53 3.83c.843-1.012 1.4'
        '-2.427 1.245-3.83-1.207.052-2.662.805-3.532 1.818-.78.896-1.454'
        '2.338-1.273 3.714 1.338.104 2.715-.688 3.559-1.701"/></svg>'
    ),
    "spotify": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 496 512">'
        '<path fill="{colour}" d="M248 8C111.1 8 0 119.1 0 256s111.1 248 248'
        ' 248 248-111.1 248-248S384.9 8 248 8zm100.7 364.9c-4.2 0-6.8-1.3'
        '-10.7-3.6-62.4-37.6-135-39.2-206.7-24.5-3.9 1-9 2.6-11.9 2.6-9.7 0'
        '-15.8-7.7-15.8-15.8 0-10.3 6.1-15.2 13.6-16.8 81.9-18.1 165.6-16.5'
        ' 237 26.2 6.1 3.9 9.7 7.4 9.7 16.5s-7.1 15.4-15.2 15.4zm26.9-65.6c'
        '-5.2 0-8.7-2.3-12.3-4.2-62.5-37-155-51.9-237.2-29.6-4.8 1.3-7.4 2.6'
        '-11.9 2.6-10.7 0-19.4-8.7-19.4-19.4s5.2-17.8 15.5-20.7c27.5-7.7 55.6'
        '-13.4 96.8-13.4 64.2 0 126.2 15.9 175 45 8.1 4.8 11.3 11 11.3 19.7'
        '-.1 10.8-8.5 20-20.1 20zm31-76.2c-5.2 0-8.4-1.3-12.9-3.9-71.2-42.5'
        '-198.5-52.7-280.9-29.6-3.6 1-8.1 2.6-12.9 2.6-13.2 0-23.3-10.3-23.3'
        '-23.6 0-13.6 8.4-21.3 17.4-23.9 35.2-10.3 74.6-15.2 117.5-15.2 73'
        ' 0 149.5 15.2 205.4 47.8 7.8 4.5 12.9 10.7 12.9 22.6 0 13.6-11 23.2'
        '-23.2 23.2z"/></svg>'
    ),
}


def _svg_pixmap(name: str, size: int, colour: str):
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return None
    markup = SVG_ICONS.get(name)
    if markup is None:
        return None
    try:
        renderer = QSvgRenderer(markup.format(colour=colour).encode("utf-8"))
        if not renderer.isValid():
            return None
        canvas = QPixmap(size, size)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing, True)
        box = renderer.viewBoxF()
        scale = min(size / box.width(), size / box.height())
        width, height = box.width() * scale, box.height() * scale
        renderer.render(painter, QRectF((size - width) / 2, (size - height) / 2,
                                        width, height))
        painter.end()
        return canvas
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# public
# --------------------------------------------------------------------------- #

def pixmap(name: str, size: int = 20, colour: str = "#E8EBF0",
           weight: float = 1.9) -> QPixmap:
    key = (name, size, colour, weight)
    if key in _cache:
        return _cache[key]

    from_svg = _svg_pixmap(name, size, colour)
    if from_svg is not None:
        _cache[key] = from_svg
        return from_svg

    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(size / BOX, size / BOX)

    stroke = QPen(QColor(colour), weight, Qt.SolidLine, Qt.RoundCap,
                  Qt.RoundJoin)
    drawer = DRAW.get(name)
    if drawer is not None:
        painter.setPen(stroke)
        painter.setBrush(Qt.NoBrush)
        drawer(painter, stroke)
    painter.end()

    _cache[key] = canvas
    return canvas


def phone_path(size: float) -> QPainterPath:
    """
    The handset as a filled path, optically centred in a size x size box.

    DRAW's functions paint straight onto a painter, which gives no way to
    measure the result - and the supplied PNGs carried their own uneven
    padding. Returning a path means the bounding box can be measured and the
    shape centred exactly, so nothing ever sits off-centre in a tile or a
    circular button.
    """
    path = QPainterPath()
    path.moveTo(6.6, 10.8)
    path.cubicTo(8.04, 13.63, 10.36, 15.94, 13.19, 17.39)
    path.lineTo(15.39, 15.19)
    path.cubicTo(15.66, 14.92, 16.06, 14.83, 16.41, 14.95)
    path.cubicTo(17.53, 15.32, 18.74, 15.52, 19.98, 15.52)
    path.cubicTo(20.53, 15.52, 20.98, 15.97, 20.98, 16.52)
    path.lineTo(20.98, 20.0)
    path.cubicTo(20.98, 20.55, 20.53, 21.0, 19.98, 21.0)
    path.cubicTo(10.59, 21.0, 2.98, 13.39, 2.98, 4.0)
    path.cubicTo(2.98, 3.45, 3.43, 3.0, 3.98, 3.0)
    path.lineTo(7.48, 3.0)
    path.cubicTo(8.03, 3.0, 8.48, 3.45, 8.48, 4.0)
    path.cubicTo(8.48, 5.25, 8.68, 6.45, 9.05, 7.57)
    path.cubicTo(9.16, 7.92, 9.08, 8.31, 8.8, 8.59)
    path.closeSubpath()

    scaled = QTransform().scale(size / BOX, size / BOX).map(path)
    bounds = scaled.boundingRect()
    return QTransform().translate(
        (size - bounds.width()) / 2 - bounds.left(),
        (size - bounds.height()) / 2 - bounds.top()).map(scaled)


def paint(painter, name: str, size: float, colour: str = "#E8EBF0",
          weight: float = 1.9) -> None:
    """
    Draw an icon straight onto an existing painter, honouring its transform.

    Use this instead of pixmap() whenever the icon is rotated or scaled. A
    pixmap is a raster: rotating a 20px one resamples it twice and the curves
    come out ragged. Painting the path lets Qt compute the geometry at the
    final angle, so it stays smooth at any rotation.

    Draws into a size x size box at the painter's current origin.
    """
    markup = SVG_ICONS.get(name)
    if markup is not None:
        try:
            from PySide6.QtSvg import QSvgRenderer
            renderer = QSvgRenderer(markup.format(colour=colour).encode("utf-8"))
            if renderer.isValid():
                renderer.render(painter, QRectF(0, 0, size, size))
                return
        except ImportError:
            pass

    drawer = DRAW.get(name)
    if drawer is None:
        return
    painter.save()
    painter.scale(size / BOX, size / BOX)
    stroke = QPen(QColor(colour), weight, Qt.SolidLine, Qt.RoundCap,
                  Qt.RoundJoin)
    painter.setPen(stroke)
    painter.setBrush(Qt.NoBrush)
    drawer(painter, stroke)
    painter.restore()


def icon(name: str, size: int = 20, colour: str = "#E8EBF0",
         weight: float = 1.9) -> QIcon:
    return QIcon(pixmap(name, size, colour, weight))
