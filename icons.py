"""
icons.py - app icon resolution for ANCS notifications.

Third-party iOS apps: the real App Store artwork is fetched from Apple's
iTunes lookup API by bundle id and cached on disk, so WhatsApp actually looks
like WhatsApp.

Apple's own apps (com.apple.*) are not in the store, so they get a tinted
gradient tile with a Segoe MDL2 glyph - visually close to the real thing.

Anything unresolved falls back to a gradient monogram tile with a stable
hash-derived hue.

Lookups never block the banner: resolve() always returns a tile immediately
and fetches in the background, so the first notification from a new app shows
a monogram and every one after it shows the real icon.
"""

from __future__ import annotations

import colorsys
import hashlib
import io
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw, ImageFont

import paths

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = paths.ICON_CACHE
LOOKUP_URL = "https://itunes.apple.com/lookup"
HTTP_TIMEOUT = 6
MISS_TTL = 7 * 24 * 3600        # re-try a failed lookup after a week

SIZE = 42                       # tile edge, px
RADIUS = 11                     # iOS-ish corner radius
_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


# --------------------------------------------------------------------------- #
# fonts
# --------------------------------------------------------------------------- #

def _font(names, size):
    for name in names:
        try:
            return ImageFont.truetype(os.path.join(_FONT_DIR, name), size)
        except OSError:
            continue
    return ImageFont.load_default()


_GLYPH_FONT = _font(["segmdl2.ttf", "SegoeIcons.ttf"], 21)
_MONO_FONT = _font(["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"], 20)


# --------------------------------------------------------------------------- #
# palettes
# --------------------------------------------------------------------------- #

# Apple system apps: (MDL2 glyph, gradient top, gradient bottom)
SYSTEM_ICONS = {
    "com.apple.mobilephone":     ("\uE717", "#54E070", "#16B33C"),
    "com.apple.MobileSMS":       ("\uE8BD", "#5BE37D", "#1BC22E"),
    "com.apple.mobilemail":      ("\uE715", "#4EA6FF", "#0A6FE0"),
    "com.apple.mobilecal":       ("\uE787", "#FF6B6B", "#E5352B"),
    "com.apple.mobileslideshow": ("\uE91B", "#FFD86B", "#FF9F0A"),
    "com.apple.facetime":        ("\uE714", "#5BE37D", "#1BC22E"),
    "com.apple.mobileaddressbook": ("\uE716", "#B8BFC9", "#7D8592"),
    "com.apple.reminders":       ("\uE8FD", "#FFB86B", "#FF9500"),
}

# Brand tints for the monogram fallback (used until artwork lands).
APP_TINTS = {
    "whatsapp":    ("#32D951", "#0DA956"),
    "phone":       ("#54E070", "#16B33C"),
    "messages":    ("#5BE37D", "#1BC22E"),
    "mail":        ("#4EA6FF", "#0A6FE0"),
    "gmail":       ("#FF6B5A", "#D93025"),
    "calendar":    ("#FF6B6B", "#E5352B"),
    "telegram":    ("#46C0EA", "#2489C8"),
    "instagram":   ("#F35A78", "#9B2FAE"),
    "slack":       ("#8E6BD6", "#4A154B"),
    "discord":     ("#7A8CF0", "#4D5FD1"),
    "outlook":     ("#4C9AFF", "#0364B8"),
    "facebook":    ("#5C8DF6", "#1877F2"),
    "snapchat":    ("#FFF066", "#F2C900"),
    "photos":      ("#FFD86B", "#FF9F0A"),
    "x / twitter": ("#4A4A4A", "#101010"),
    "iphone":      ("#B8BFC9", "#7D8592"),
}


def _hex(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _tint(name: str):
    key = name.strip().lower()
    if key in APP_TINTS:
        top, bot = APP_TINTS[key]
        return _hex(top), _hex(bot)
    seed = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    top = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(seed, 0.55, 0.98))
    bot = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(seed, 0.82, 0.76))
    return top, bot


# --------------------------------------------------------------------------- #
# tile drawing
# --------------------------------------------------------------------------- #

def _round_mask() -> Image.Image:
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], RADIUS, fill=255)
    return mask


def _gradient(top, bot) -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE))
    d = ImageDraw.Draw(img)
    for y in range(SIZE):
        t = y / max(1, SIZE - 1)
        d.line([(0, y), (SIZE, y)],
               fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,))
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(img, (0, 0), _round_mask())
    return out


def _centered(tile: Image.Image, text: str, font) -> Image.Image:
    d = ImageDraw.Draw(tile)
    box = d.textbbox((0, 0), text, font=font)
    x = (SIZE - (box[2] - box[0])) / 2 - box[0]
    y = (SIZE - (box[3] - box[1])) / 2 - box[1]
    d.text((x, y), text, font=font, fill=(255, 255, 255, 240))
    return tile


def _system_tile(bundle_id: str):
    spec = SYSTEM_ICONS.get(bundle_id)
    if not spec:
        return None
    glyph, top, bot = spec
    return _centered(_gradient(_hex(top), _hex(bot)), glyph, _GLYPH_FONT)


def _monogram_tile(app_name: str) -> Image.Image:
    top, bot = _tint(app_name)
    glyph = next((c for c in app_name if c.isalnum()), "?").upper()
    return _centered(_gradient(top, bot), glyph, _MONO_FONT)


def _tile_from_bytes(data: bytes):
    try:
        art = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None
    art = art.resize((SIZE, SIZE), Image.LANCZOS)
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(art, (0, 0), _round_mask())
    return out


# --------------------------------------------------------------------------- #
# disk cache + fetch
# --------------------------------------------------------------------------- #

def _safe(bundle_id: str) -> str:
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in bundle_id)[:120]


def _png_path(bundle_id: str) -> str:
    return os.path.join(CACHE_DIR, _safe(bundle_id) + ".png")


def _miss_path(bundle_id: str) -> str:
    return os.path.join(CACHE_DIR, _safe(bundle_id) + ".miss")


def _missed_recently(bundle_id: str) -> bool:
    try:
        return (time.time() - os.path.getmtime(_miss_path(bundle_id))) < MISS_TTL
    except OSError:
        return False


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ancs_notifier/1.0"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def _fetch_artwork(bundle_id: str):
    query = urllib.parse.urlencode({"bundleId": bundle_id, "entity": "software"})
    payload = json.loads(_http_get(f"{LOOKUP_URL}?{query}").decode("utf-8", "replace"))
    results = payload.get("results") or []
    if not results:
        return None
    entry = results[0]
    url = (entry.get("artworkUrl512") or entry.get("artworkUrl100")
           or entry.get("artworkUrl60"))
    return _http_get(url) if url else None


_mem: dict[str, Image.Image] = {}
_inflight: set[str] = set()
_lock = threading.Lock()


def _worker(bundle_id: str) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        data = _fetch_artwork(bundle_id)
        if data and _tile_from_bytes(data) is not None:
            with open(_png_path(bundle_id), "wb") as fh:
                fh.write(data)
            with _lock:
                _mem.pop(bundle_id, None)      # next resolve() picks up the art
            print(f"  (icon cached: {bundle_id})")
        else:
            open(_miss_path(bundle_id), "wb").close()
    except Exception as exc:
        try:
            open(_miss_path(bundle_id), "wb").close()
        except OSError:
            pass
        print(f"  (icon lookup failed for {bundle_id}: {exc})")
    finally:
        with _lock:
            _inflight.discard(bundle_id)


def _spawn(bundle_id: str) -> None:
    with _lock:
        if bundle_id in _inflight:
            return
        _inflight.add(bundle_id)
    threading.Thread(target=_worker, args=(bundle_id,),
                     name=f"icon:{bundle_id}", daemon=True).start()


def resolve(bundle_id: str | None, app_name: str) -> Image.Image:
    """Return a SIZE x SIZE RGBA tile for this app. Never blocks on network."""
    key = (bundle_id or "").strip()
    with _lock:
        cached = _mem.get(key or app_name)
    if cached is not None:
        return cached

    tile = None
    if key:
        try:
            with open(_png_path(key), "rb") as fh:
                tile = _tile_from_bytes(fh.read())
        except OSError:
            tile = None

    if tile is None:
        tile = _system_tile(key)

    if tile is None:
        tile = _monogram_tile(app_name or "iPhone")
        if key and key not in SYSTEM_ICONS and not _missed_recently(key):
            _spawn(key)

    with _lock:
        _mem[key or app_name] = tile
    return tile


def prefetch(bundle_ids) -> None:
    """Warm the cache at startup so known apps show real artwork immediately."""
    for bundle_id in bundle_ids:
        if not bundle_id or bundle_id in SYSTEM_ICONS:
            continue
        if os.path.exists(_png_path(bundle_id)) or _missed_recently(bundle_id):
            continue
        _spawn(bundle_id)
