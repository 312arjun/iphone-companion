"""
appicon.py - the tray and application icon.

The brand artwork in assets/app_icon.png is the icon. The tray still needs to
show connection state, so a status dot is composited onto the bottom-right
corner rather than replacing the artwork with a drawn stand-in.

If the asset is missing (someone cloned without running make_icon.py) this
falls back to the drawn phone-and-dot mark, so the app always has an icon.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

import paths

ASSET = paths.bundled("assets", "app_icon.png")
ICO = paths.bundled("assets", "app.ico")

DOT_COLORS = {
    "listening":    ((52, 199, 89), (26, 150, 60)),      # green
    "reconnecting": ((255, 179, 64), (214, 130, 20)),    # amber
    "paused":       ((142, 142, 147), (99, 99, 104)),    # grey
}

_master: Image.Image | None = None
_missing = False


def _load() -> Image.Image | None:
    global _master, _missing
    if _master is not None or _missing:
        return _master
    try:
        image = Image.open(ASSET).convert("RGBA")
        # Crop to the artwork. The master PNG keeps transparent margin around
        # the tile, so resizing the whole canvas left the icon floating inside
        # its box - visible as a gap between the tile and the sidebar.
        box = image.getchannel("A").getbbox()
        if box:
            image = image.crop(box)
        side = max(image.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.alpha_composite(image, ((side - image.width) // 2,
                                       (side - image.height) // 2))
        _master = square
    except Exception:
        _missing = True
    return _master


def _status_dot(image: Image.Image, state: str) -> Image.Image:
    """Bottom-right dot with a dark ring, so it reads on any wallpaper."""
    top, bottom = DOT_COLORS.get(state, DOT_COLORS["reconnecting"])
    size = image.width
    diameter = size * 0.40
    x = size - diameter - size * 0.02
    y = size - diameter - size * 0.02

    d = ImageDraw.Draw(image)
    d.ellipse([x - size * 0.03, y - size * 0.03,
               x + diameter + size * 0.03, y + diameter + size * 0.03],
              fill=(12, 16, 22, 255))
    d.ellipse([x, y, x + diameter, y + diameter], fill=bottom + (255,))
    inset = diameter * 0.16
    d.ellipse([x + inset, y + inset, x + diameter - inset,
               y + diameter - inset], fill=top + (255,))
    return image


def _drawn(state: str, px: int) -> Image.Image:
    """Fallback mark: a phone body with a status dot."""
    s = px / 64.0

    def box(*coords):
        return [c * s for c in coords]

    top, bottom = DOT_COLORS.get(state, DOT_COLORS["reconnecting"])
    image = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle(box(17, 3, 47, 61), radius=9 * s, fill=(28, 32, 40, 255))
    d.rounded_rectangle(box(20, 9, 44, 53), radius=5 * s, fill=(236, 240, 246, 255))
    d.ellipse(box(33, 33, 61, 61), fill=bottom + (255,))
    d.ellipse(box(35.5, 35.5, 58.5, 58.5), fill=top + (255,))
    return image


def background_colour() -> str:
    """
    The icon tile's own background colour, as hex.

    The artwork's rounded corners let the sidebar show through, which read as
    a mismatched box sitting on top of it. Painting the label behind the icon
    in this colour fills those corners so the mark looks like one solid tile
    instead of an overlay.
    """
    master = _load()
    if master is None:
        return "#1C2027"
    try:
        # The most common fully-opaque colour is the tile; the blue flag and
        # white phone are a minority of the pixels.
        small = master.resize((32, 32), Image.LANCZOS)
        counts: dict[tuple, int] = {}
        for pixel in small.getdata():
            if pixel[3] > 200:
                counts[pixel[:3]] = counts.get(pixel[:3], 0) + 1
        if not counts:
            return "#1C2027"
        red, green, blue = max(counts, key=counts.get)
        return f"#{red:02X}{green:02X}{blue:02X}"
    except Exception:
        return "#1C2027"


def make(state: str = "listening", px: int = 64) -> Image.Image:
    """Tray icon at the requested size, with the state dot applied."""
    master = _load()
    if master is None:
        return _drawn(state, px)
    icon = master.resize((px, px), Image.LANCZOS)
    return _status_dot(icon, state)


def plain(px: int = 256) -> Image.Image:
    """The artwork with no status dot - for windows and about screens."""
    master = _load()
    if master is None:
        return _drawn("listening", px)
    return master.resize((px, px), Image.LANCZOS)


def ico_path() -> str | None:
    return ICO if os.path.exists(ICO) else None


def save_ico(path: str, state: str = "listening") -> str:
    """
    Kept for build.py. Prefers the real .ico produced by make_icon.py and
    only synthesises one from the drawn mark as a last resort.
    """
    existing = ico_path()
    sizes = [16, 24, 32, 48, 64, 128, 256]
    if existing and os.path.abspath(existing) != os.path.abspath(path):
        Image.open(existing).save(path, format="ICO",
                                  sizes=[(n, n) for n in sizes])
        return path
    if existing:
        return existing
    base = plain(256)
    base.save(path, format="ICO", sizes=[(n, n) for n in sizes])
    return path
