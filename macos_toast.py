"""
macos_toast.py - macOS-style notification banners on Windows.

Renders a frosted-glass rounded card in the top-right of the primary display,
slides it in from the right edge, holds it, then slides back out. The frost is
real: the screen behind the card is captured, Gaussian-blurred and tinted, so
the banner picks up the wallpaper / window colours underneath it. The tint
direction (light or dark) is chosen from the brightness of that capture.

Two layouts:
  * default - app icon, title, body, optional capsule action buttons
  * "call"  - initials avatar, caller name, "from your iPhone", and round
              red / green handset buttons, matching the macOS call banner

Four things are load-bearing and easy to break:

  * ImageDraw does NOT antialias. Every shape is drawn into a 4x overlay and
    downscaled with LANCZOS (see _Hi). Drawing straight onto the card at 1x
    gives visibly stair-stepped corners and circles.
  * Text is drawn at 1x, after the overlay is composited. FreeType already
    antialiases glyphs, and supersampling them softens the stems.
  * Banner windows must never overlap. Each one bakes a screenshot of its own
    background, so an overlapping neighbour gets photographed into the image
    and lingers there after it has gone. GAP >= 2 * SHADOW_PAD guarantees it.
  * Exit is a reverse slide, not an alpha fade. Fading a window whose content
    is a photo of the background blends that photo against the live desktop,
    which ghosts. Sliding keeps it opaque.

Requires Pillow (pip install pillow). Tkinter ships with CPython.

    from macos_toast import show_toast, dismiss_toast
    show_toast("Phone", "Alex Whitfield", "", "com.apple.mobilephone",
               actions=[("Answer", answer_fn, "positive"),
                        ("Decline", decline_fn, "negative")],
               style="call", key=uid)
    dismiss_toast(uid)          # the call was picked up on the phone

Standalone demo:  python macos_toast.py
"""

from __future__ import annotations

import ctypes
import os
import queue
import threading
import time
import tkinter as tk
from collections import deque

from PIL import (Image, ImageDraw, ImageFilter, ImageFont, ImageGrab, ImageStat,
                 ImageTk)

import icons


# --------------------------------------------------------------------------- #
# DPI awareness - must happen before the first Tk root exists, otherwise Tk
# reports scaled coordinates and ImageGrab reports physical ones.
# --------------------------------------------------------------------------- #

def _init_dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_init_dpi()


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #

SS = 4                          # supersample factor for drawn shapes (see _Hi)

CARD_W, CARD_H = 372, 78
RADIUS = 18
MARGIN = 20                     # gap from the screen edges
SHADOW_PAD = 12                 # window padding that holds the drop shadow
GAP = 26                        # MUST be >= 2 * SHADOW_PAD (see module docs)
SHADOW_BLUR = 9
SHADOW_DY = 4
SHADOW_ALPHA = 80

ICON_SIZE = icons.SIZE
PAD_L = 12
PAD_R = 14
TEXT_GAP = 12

WIN_W = CARD_W + 2 * SHADOW_PAD
WIN_H = CARD_H + 2 * SHADOW_PAD
TEXT_X = PAD_L + ICON_SIZE + TEXT_GAP

assert GAP >= 2 * SHADOW_PAD, "banner windows would overlap and bake ghosts"


# --------------------------------------------------------------------------- #
# theme
#
# The frost is a blur of the desktop, so a dark desktop needs a dark card or
# the text loses contrast. The tint is picked per banner from the capture.
# --------------------------------------------------------------------------- #

LIGHT = {
    "tint": (255, 255, 255),
    "tint_amount": 0.62,
    "border": (255, 255, 255, 150),
    "title": (28, 28, 30),
    "body": (86, 86, 92),
    "avatar": ((188, 190, 196), (150, 152, 160)),
}
DARK = {
    "tint": (22, 22, 26),
    "tint_amount": 0.58,
    "border": (255, 255, 255, 46),
    "title": (246, 246, 248),
    "body": (178, 178, 188),
    "avatar": ((118, 120, 130), (78, 80, 90)),
}
DARK_THRESHOLD = 118            # mean luminance below this -> dark card

FROST_BLUR = 18

# default layout: capsule buttons stacked on the right
BTN_COL_W = 84
BTN_INSET = 8
BTN_GAP = 6
BTN_RADIUS = 10
BTN_H_MAX = 34
BTN_LABEL = (255, 255, 255, 255)

# call layout: round handset buttons, side by side (decline left, accept right)
CALL_AVATAR = 44
CALL_BTN_D = 38
CALL_BTN_GAP = 10
CALL_BTN_INSET = 12
CALL_SUBTITLE = "from your iPhone"

ACTION_FILLS = {
    "positive": (52, 199, 89),
    "negative": (255, 69, 58),
    "neutral":  (10, 132, 255),
}
HOVER_LIFT = 26                 # how much lighter a hovered button gets

# Segoe MDL2 Assets: one handset glyph, rotated for decline - the same trick
# macOS uses. If your Windows build lacks the font, set USE_GLYPH_BUTTONS to
# False and the call buttons fall back to text labels.
USE_GLYPH_BUTTONS = True
GLYPH_PHONE = "\uE717"
# PIL rotates counter-clockwise, so negative = clockwise. -135 hangs the
# handset downward, as on iOS. Nudge to -90 or -180 if a future Segoe MDL2
# revision ships the glyph at a different base angle.
DECLINE_ROTATION = -135

TEXT_W_PLAIN = CARD_W - TEXT_X - PAD_R
TEXT_W_ACTIONS = CARD_W - TEXT_X - BTN_COL_W - BTN_INSET - 8

# timing
MAX_VISIBLE = 3
HOLD_MS = 5200
HOLD_ACTION_MS = 28000          # actionable banners stay for a ring's length
SLIDE_IN_MS = 300
SLIDE_IN_FRAMES = 12
SLIDE_OUT_MS = 220
SLIDE_OUT_FRAMES = 10


# --------------------------------------------------------------------------- #
# fonts
# --------------------------------------------------------------------------- #

_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def _font(names, size):
    for name in names:
        try:
            return ImageFont.truetype(os.path.join(_FONT_DIR, name), size)
        except OSError:
            continue
    return ImageFont.load_default()


_BOLD = ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"]
_REG = ["segoeui.ttf", "arial.ttf"]

TITLE_FONT = _font(_BOLD, 15)
BODY_FONT = _font(_REG, 14)
BTN_FONT = _font(_BOLD, 12)
EMOJI_FONT = _font(["seguiemj.ttf"], 15)

_sized_fonts: dict[tuple, object] = {}


def _sized(names, px):
    """Fonts at arbitrary (supersampled) sizes, cached."""
    key = (tuple(names), px)
    if key not in _sized_fonts:
        _sized_fonts[key] = _font(list(names), px)
    return _sized_fonts[key]


# --------------------------------------------------------------------------- #
# emoji-aware text drawing
#
# Pillow can only use one font per draw.text() call, so mixed text is split
# into runs and each run is drawn with the font that can actually render it.
# --------------------------------------------------------------------------- #

def _is_emoji(ch: str) -> bool:
    o = ord(ch)
    return (
        0x1F000 <= o <= 0x1FAFF
        or 0x2600 <= o <= 0x27BF
        or 0x1F1E6 <= o <= 0x1F1FF
        or o in (0x200D, 0xFE0F, 0x20E3, 0x2B50, 0x2B55)
    )


def _runs(text: str):
    out, cur, cur_kind = [], "", None
    for ch in text:
        kind = _is_emoji(ch)
        if cur and kind != cur_kind:
            out.append((cur, cur_kind))
            cur = ""
        cur, cur_kind = cur + ch, kind
    if cur:
        out.append((cur, cur_kind))
    return out


def _mlen(text: str, font) -> float:
    return sum((EMOJI_FONT if is_e else font).getlength(run)
               for run, is_e in _runs(text))


def _draw_text(draw, xy, text, font, fill):
    x, y = xy
    for run, is_e in _runs(text):
        f = EMOJI_FONT if is_e else font
        try:
            if is_e:
                draw.text((x, y), run, font=f, embedded_color=True)
            else:
                draw.text((x, y), run, font=f, fill=fill)
        except Exception:
            draw.text((x, y), run, font=font, fill=fill)
        x += f.getlength(run)


def _ellipsize(text: str, font, max_w: float) -> str:
    if _mlen(text, font) <= max_w:
        return text
    s = text
    while s and _mlen(s + "\u2026", font) > max_w:
        s = s[:-1]
    return (s.rstrip() + "\u2026") if s else ""


def _wrap(text: str, font, max_w: float, max_lines: int) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    words, lines, cur, i = text.split(" "), [], "", 0
    while i < len(words):
        cand = words[i] if not cur else cur + " " + words[i]
        if _mlen(cand, font) <= max_w:
            cur, i = cand, i + 1
        elif not cur:
            lines.append(_ellipsize(words[i], font, max_w))
            i += 1
            if len(lines) == max_lines:
                break
        else:
            lines.append(cur)
            cur = ""
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
        cur = ""
    if (i < len(words) or cur) and lines:
        lines[-1] = _ellipsize(lines[-1] + " \u2026", font, max_w)
    return lines


# --------------------------------------------------------------------------- #
# supersampled shape layer
#
# ImageDraw has no antialiasing at any size, so every shape is drawn at SS x
# scale and downscaled with LANCZOS. Methods take 1x coordinates and scale
# internally, so callers stay readable.
# --------------------------------------------------------------------------- #

class _Hi:
    def __init__(self, w=CARD_W, h=CARD_H):
        self.w, self.h = w, h
        self.img = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    @staticmethod
    def _s(box):
        return [v * SS for v in box]

    def rounded(self, box, radius, **kw):
        self.d.rounded_rectangle(self._s(box), radius * SS, **kw)

    def ellipse(self, box, **kw):
        self.d.ellipse(self._s(box), **kw)

    def paste_centered(self, sprite, cx, cy):
        """sprite is already at SS scale."""
        self.img.alpha_composite(
            sprite,
            (int(cx * SS - sprite.width / 2), int(cy * SS - sprite.height / 2)),
        )

    def flatten(self):
        return self.img.resize((self.w, self.h), Image.LANCZOS)


def _glyph_sprite(char, px, color, rotate=0):
    """Render one icon-font glyph at SS scale, optionally rotated."""
    size = px * SS
    font = _sized(("segmdl2.ttf", "SegoeIcons.ttf"), size)
    canvas = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    box = d.textbbox((0, 0), char, font=font)
    d.text((size - (box[2] - box[0]) / 2 - box[0],
            size - (box[3] - box[1]) / 2 - box[1]),
           char, font=font, fill=color)
    if rotate:
        canvas = canvas.rotate(rotate, resample=Image.BICUBIC, expand=False)
    return canvas


def _person_sprite(px, color):
    """
    A drawn silhouette, for callers with no letters to make initials from (an
    unknown number). Primitives only, so it can never render as tofu.
    """
    size = px * SS
    sprite = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(sprite)
    head_r = size * 0.19
    cx, head_cy = size / 2, size * 0.34
    d.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r],
              fill=color)
    body_w, body_h = size * 0.62, size * 0.46
    d.ellipse([cx - body_w / 2, size * 0.58, cx + body_w / 2, size * 0.58 + body_h],
              fill=color)
    return sprite


def _initials(name: str) -> str:
    parts = [p for p in (name or "").split() if any(c.isalpha() for c in p)]
    if not parts:
        return ""
    return "".join(next(c for c in p if c.isalpha()) for p in parts[:2]).upper()


def _lift(rgb, amount):
    return tuple(min(255, c + amount) for c in rgb)


# --------------------------------------------------------------------------- #
# layout: where the clickable things are (1x card coordinates)
# --------------------------------------------------------------------------- #

def _capsule_rects(count):
    if count <= 0:
        return []
    x0 = CARD_W - BTN_INSET - BTN_COL_W
    x1 = CARD_W - BTN_INSET
    if count == 1:
        h = min(BTN_H_MAX, CARD_H - 2 * BTN_INSET)
        y0 = (CARD_H - h) / 2
        return [(x0, y0, x1, y0 + h)]
    total = CARD_H - 2 * BTN_INSET
    h = (total - BTN_GAP * (count - 1)) / count
    return [(x0, BTN_INSET + i * (h + BTN_GAP), x1, BTN_INSET + i * (h + BTN_GAP) + h)
            for i in range(count)]


def _circle_rects(count):
    if count <= 0:
        return []
    total = count * CALL_BTN_D + (count - 1) * CALL_BTN_GAP
    x = CARD_W - CALL_BTN_INSET - total
    y = (CARD_H - CALL_BTN_D) / 2
    rects = []
    for _ in range(count):
        rects.append((x, y, x + CALL_BTN_D, y + CALL_BTN_D))
        x += CALL_BTN_D + CALL_BTN_GAP
    return rects


def button_rects(count, style=None):
    return _circle_rects(count) if style == "call" else _capsule_rects(count)


def order_actions(actions, style=None):
    """The call banner puts decline on the left, accept on the right."""
    if style != "call" or not actions:
        return actions
    return sorted(actions,
                  key=lambda a: 0 if (len(a) > 2 and a[2] == "negative") else 1)


# --------------------------------------------------------------------------- #
# painting
# --------------------------------------------------------------------------- #

def _paint_capsules(hi, actions, hover):
    for index, (rect, action) in enumerate(zip(_capsule_rects(len(actions)), actions)):
        kind = action[2] if len(action) > 2 else "neutral"
        fill = ACTION_FILLS.get(kind, ACTION_FILLS["neutral"])
        if hover == index:
            fill = _lift(fill, HOVER_LIFT)
        hi.rounded(rect, BTN_RADIUS, fill=fill + (255,))


def _paint_circles(hi, actions, hover):
    for index, (rect, action) in enumerate(zip(_circle_rects(len(actions)), actions)):
        x0, y0, x1, y1 = rect
        kind = action[2] if len(action) > 2 else "neutral"
        fill = ACTION_FILLS.get(kind, ACTION_FILLS["neutral"])
        if hover == index:
            fill = _lift(fill, HOVER_LIFT)
        hi.ellipse(rect, fill=fill + (255,))

        if USE_GLYPH_BUTTONS:
            rotate = DECLINE_ROTATION if kind == "negative" else 0
            sprite = _glyph_sprite(GLYPH_PHONE, 17, (255, 255, 255, 255), rotate)
            hi.paste_centered(sprite, (x0 + x1) / 2, (y0 + y1) / 2)


def _paint_avatar(hi, theme, name):
    box = (PAD_L, (CARD_H - CALL_AVATAR) / 2,
           PAD_L + CALL_AVATAR, (CARD_H - CALL_AVATAR) / 2 + CALL_AVATAR)
    top, bottom = theme["avatar"]

    span = CALL_AVATAR * SS
    grad = Image.new("RGBA", (span, span))
    gd = ImageDraw.Draw(grad)
    for y in range(span):
        t = y / max(1, span - 1)
        gd.line([(0, y), (span, y)],
                fill=tuple(int(top[i] + (bottom[i] - top[i]) * t)
                           for i in range(3)) + (255,))
    ring = Image.new("L", (span, span), 0)
    ImageDraw.Draw(ring).ellipse([0, 0, span - 1, span - 1], fill=255)
    grad.putalpha(ring)
    hi.img.alpha_composite(grad, (int(box[0] * SS), int(box[1] * SS)))

    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    text = _initials(name)
    if text:
        font = _sized(tuple(_BOLD), 17 * SS)
        tb = hi.d.textbbox((0, 0), text, font=font)
        hi.d.text((cx * SS - (tb[2] - tb[0]) / 2 - tb[0],
                   cy * SS - (tb[3] - tb[1]) / 2 - tb[1]),
                  text, font=font, fill=(255, 255, 255, 235))
    else:
        hi.paste_centered(_person_sprite(26, (255, 255, 255, 225)), cx, cy)


def _center_label(d, rect, text, pad):
    x0, y0, x1, y1 = rect
    text = _ellipsize(text, BTN_FONT, (x1 - x0) - pad)
    tb = d.textbbox((0, 0), text, font=BTN_FONT)
    d.text((x0 + ((x1 - x0) - (tb[2] - tb[0])) / 2 - tb[0],
            y0 + ((y1 - y0) - (tb[3] - tb[1])) / 2 - tb[1]),
           text, font=BTN_FONT, fill=BTN_LABEL)


def _paint_content(base, theme, item, hover):
    """Shapes into a supersampled overlay, then text at 1x on top."""
    actions = item["actions"]
    style = item.get("style")
    card = base.copy()

    hi = _Hi()
    if style == "call":
        _paint_avatar(hi, theme, item["title"])
        _paint_circles(hi, actions, hover)
    elif actions:
        _paint_capsules(hi, actions, hover)
    card.alpha_composite(hi.flatten())

    if style != "call":
        card.alpha_composite(icons.resolve(item.get("bundle_id"), item["app"]),
                             (PAD_L, (CARD_H - ICON_SIZE) // 2))

    if style == "call":
        text_x = PAD_L + CALL_AVATAR + TEXT_GAP
        rects = _circle_rects(len(actions))
        right = rects[0][0] - 10 if rects else CARD_W - PAD_R
        text_w = right - text_x
        headline = _ellipsize(item["title"] or item["app"], TITLE_FONT, text_w)
        lines = [_ellipsize(item["body"] or CALL_SUBTITLE, BODY_FONT, text_w)]
    else:
        text_x = TEXT_X
        text_w = TEXT_W_ACTIONS if actions else TEXT_W_PLAIN
        headline = _ellipsize(item["title"] or item["app"], TITLE_FONT, text_w)
        lines = _wrap(item["body"], BODY_FONT, text_w, 1 if actions else 2)

    d = ImageDraw.Draw(card)
    title_h, body_h = 19, 18
    block = title_h + (2 + body_h * len(lines) if lines else 0)
    y = (CARD_H - block) // 2

    _draw_text(d, (text_x, y), headline, TITLE_FONT, theme["title"])
    y += title_h + 2
    for line in lines:
        _draw_text(d, (text_x, y), line, BODY_FONT, theme["body"])
        y += body_h

    # labels at 1x, so the stems stay crisp
    if style != "call" and actions:
        for rect, action in zip(_capsule_rects(len(actions)), actions):
            _center_label(d, rect, action[0], 10)
    elif style == "call" and not USE_GLYPH_BUTTONS:
        for rect, action in zip(_circle_rects(len(actions)), actions):
            _center_label(d, rect, action[0], 4)

    return card


# --------------------------------------------------------------------------- #
# compositing
# --------------------------------------------------------------------------- #

class _Composer:
    """
    Holds the captured background strip plus the rendered card, and can
    composite the banner at any x. Kept alive for the banner's lifetime so the
    exit slide can be built lazily instead of paying for it up front.
    """

    def __init__(self, item, final_x, y, screen_w):
        self.final_x = final_x
        self.screen_w = screen_w
        self.strip = self._grab(final_x, y, screen_w)

        window_bg = self.strip.crop((0, 0, WIN_W, WIN_H))
        theme = self._pick_theme(window_bg)
        base, mask = self._frost(window_bg, theme)
        self.shadow = self._shadow(mask)
        self.card = _paint_content(base, theme, item, None)
        self._hover_cards = {
            i: _paint_content(base, theme, item, i)
            for i in range(len(item["actions"]))
        }

    # -- capture ---------------------------------------------------------- #

    @staticmethod
    def _grab(final_x, y, screen_w):
        """
        Capture everything the window will ever cover, plus right-edge padding
        so frames hanging off-screen still have pixels to composite on.
        """
        raw = ImageGrab.grab(bbox=(final_x, y, screen_w, y + WIN_H), all_screens=True)
        if raw.mode != "RGB":
            raw = raw.convert("RGB")
        strip = Image.new("RGB", (raw.width + WIN_W, WIN_H))
        strip.paste(raw, (0, 0))
        edge = raw.crop((raw.width - 1, 0, raw.width, WIN_H)).resize((WIN_W, WIN_H))
        strip.paste(edge, (raw.width, 0))
        return strip

    @staticmethod
    def _pick_theme(window_bg):
        card_area = window_bg.crop(
            (SHADOW_PAD, SHADOW_PAD, SHADOW_PAD + CARD_W, SHADOW_PAD + CARD_H)
        )
        mean = ImageStat.Stat(card_area.convert("L")).mean[0]
        return DARK if mean < DARK_THRESHOLD else LIGHT

    # -- card base -------------------------------------------------------- #

    @staticmethod
    def _frost(window_bg, theme):
        frost = window_bg.filter(ImageFilter.GaussianBlur(FROST_BLUR)).crop(
            (SHADOW_PAD, SHADOW_PAD, SHADOW_PAD + CARD_W, SHADOW_PAD + CARD_H)
        )
        frost = Image.blend(frost, Image.new("RGB", frost.size, theme["tint"]),
                            theme["tint_amount"])

        # supersampled corner mask - this is what makes the card edge smooth
        hi_mask = Image.new("L", (CARD_W * SS, CARD_H * SS), 0)
        ImageDraw.Draw(hi_mask).rounded_rectangle(
            [0, 0, CARD_W * SS - 1, CARD_H * SS - 1], RADIUS * SS, fill=255
        )
        mask = hi_mask.resize((CARD_W, CARD_H), Image.LANCZOS)

        card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        card.paste(frost, (0, 0), mask)

        edge = _Hi()
        edge.rounded((0, 0, CARD_W - 1, CARD_H - 1), RADIUS,
                     outline=theme["border"], width=SS)
        card.alpha_composite(edge.flatten())
        return card, mask

    @staticmethod
    def _shadow(mask):
        alpha = Image.new("L", (WIN_W, WIN_H), 0)
        alpha.paste(mask.point(lambda v: v * SHADOW_ALPHA // 255),
                    (SHADOW_PAD, SHADOW_PAD + SHADOW_DY))
        alpha = alpha.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
        shadow = Image.new("RGBA", (WIN_W, WIN_H), (0, 0, 0, 0))
        shadow.putalpha(alpha)
        return shadow

    # -- frames ----------------------------------------------------------- #

    def at(self, x, card=None):
        bg = self.strip.crop((x - self.final_x, 0,
                              x - self.final_x + WIN_W, WIN_H)).convert("RGBA")
        bg.alpha_composite(self.shadow)
        bg.alpha_composite(card if card is not None else self.card,
                           (SHADOW_PAD, SHADOW_PAD))
        return bg.convert("RGB")

    def slide_in(self):
        """Ease-out from off the right edge to the resting position."""
        frames = []
        for i in range(SLIDE_IN_FRAMES):
            t = (i + 1) / SLIDE_IN_FRAMES
            eased = 1 - (1 - t) ** 3
            x = int(round(self.screen_w + (self.final_x - self.screen_w) * eased))
            frames.append((x, self.at(x)))
        return frames

    def slide_out(self):
        """Ease-in back out past the right edge, ending fully off-screen."""
        frames = []
        for i in range(SLIDE_OUT_FRAMES):
            t = (i + 1) / SLIDE_OUT_FRAMES
            eased = t ** 2
            x = int(round(self.final_x + (self.screen_w - self.final_x) * eased))
            frames.append((x, self.at(x)))
        return frames

    def hover(self, index):
        card = self._hover_cards.get(index)
        return None if card is None else self.at(self.final_x, card)


# --------------------------------------------------------------------------- #
# window
# --------------------------------------------------------------------------- #

_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080


def _no_activate(widget) -> None:
    """Keep the banner from stealing focus or landing in Alt-Tab."""
    try:
        hwnd = widget.winfo_id()
        u = ctypes.windll.user32
        ex = u.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        u.SetWindowLongW(hwnd, _GWL_EXSTYLE,
                         ex | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW)
    except Exception:
        pass


class _Banner:
    def __init__(self, server, slot, composer, y, item):
        self.server, self.slot, self.composer, self.y = server, slot, composer, y
        self.actions = item["actions"]
        self.hold_ms = item["hold_ms"]
        self.key = item.get("key")
        self.timer = None
        self.dead = False
        self.leaving = False
        self.hovered = None

        # hit regions in canvas coordinates (card is inset by the shadow pad)
        self.hits = [(x0 + SHADOW_PAD, y0 + SHADOW_PAD,
                      x1 + SHADOW_PAD, y1 + SHADOW_PAD)
                     for (x0, y0, x1, y1)
                     in button_rects(len(self.actions), item.get("style"))]

        frames = composer.slide_in()
        self.win = tk.Toplevel(server.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.0)
        self.win.geometry(f"{WIN_W}x{WIN_H}+{frames[0][0]}+{y}")

        self.canvas = tk.Canvas(self.win, width=WIN_W, height=WIN_H,
                                highlightthickness=0, bd=0, takefocus=0)
        self.canvas.pack()
        self.photos = [ImageTk.PhotoImage(img) for _, img in frames]
        self.xs = [x for x, _ in frames]
        self.hover_photos = {}
        for index in range(len(self.actions)):
            image = composer.hover(index)
            if image is not None:
                self.hover_photos[index] = ImageTk.PhotoImage(image)
        self.item = self.canvas.create_image(0, 0, anchor="nw", image=self.photos[0])

        _no_activate(self.win)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Enter>", lambda _e: self._cancel())      # hover holds it
        self.canvas.bind("<Leave>", self._on_leave)

        self._slide_in(0)

    # -- input ------------------------------------------------------------ #

    def _hit_index(self, x, y):
        for index, (x0, y0, x1, y1) in enumerate(self.hits):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return index
        return None

    def _on_motion(self, event):
        if self.dead or self.leaving or not self.actions:
            return
        index = self._hit_index(event.x, event.y)
        if index == self.hovered:
            return
        self.hovered = index
        photo = self.hover_photos.get(index) if index is not None else self.photos[-1]
        if photo is not None:
            self.canvas.itemconfig(self.item, image=photo)
        self.canvas.configure(cursor="hand2" if index is not None else "")

    def _on_leave(self, _event):
        if not self.dead and not self.leaving and self.hovered is not None:
            self.hovered = None
            self.canvas.itemconfig(self.item, image=self.photos[-1])
            self.canvas.configure(cursor="")
        self._arm()

    def _on_click(self, event):
        if self.leaving:
            return
        index = self._hit_index(event.x, event.y)
        self.dismiss()
        if index is None:
            return
        callback = self.actions[index][1]
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            print(f"  (action '{self.actions[index][0]}' failed: {exc})")

    # -- animation -------------------------------------------------------- #

    def _slide_in(self, i):
        if self.dead or self.leaving:
            return
        self.win.geometry(f"+{self.xs[i]}+{self.y}")
        self.canvas.itemconfig(self.item, image=self.photos[i])
        self.win.attributes("-alpha", 0.4 + 0.6 * (i + 1) / len(self.photos))
        if i + 1 < len(self.photos):
            self.win.after(max(1, SLIDE_IN_MS // SLIDE_IN_FRAMES),
                           self._slide_in, i + 1)
        else:
            self.win.attributes("-alpha", 1.0)
            self._arm()

    def _arm(self):
        self._cancel()
        if not self.dead and not self.leaving:
            self.timer = self.win.after(self.hold_ms, self.dismiss)

    def _cancel(self):
        if self.timer is not None:
            try:
                self.win.after_cancel(self.timer)
            except Exception:
                pass
            self.timer = None

    def dismiss(self):
        """Slide out to the right. Opaque throughout, so nothing ghosts."""
        if self.dead or self.leaving:
            return
        self.leaving = True
        self._cancel()
        self.canvas.configure(cursor="")
        try:
            frames = self.composer.slide_out()
            self.out_photos = [ImageTk.PhotoImage(img) for _, img in frames]
            self.out_xs = [x for x, _ in frames]
        except Exception:
            self._destroy()
            return
        self._slide_out(0)

    def _slide_out(self, i):
        if self.dead:
            return
        if i >= len(self.out_photos):
            self._destroy()
            return
        try:
            self.win.geometry(f"+{self.out_xs[i]}+{self.y}")
            self.canvas.itemconfig(self.item, image=self.out_photos[i])
        except Exception:
            self._destroy()
            return
        self.win.after(max(1, SLIDE_OUT_MS // SLIDE_OUT_FRAMES),
                       self._slide_out, i + 1)

    def _destroy(self):
        self.dead = True
        try:
            self.win.destroy()
        except Exception:
            pass
        self.server.release(self.slot, self.key)


# --------------------------------------------------------------------------- #
# server: one Tk root on a daemon thread, fed by a queue
# --------------------------------------------------------------------------- #

class _Server:
    def __init__(self):
        self.inbox = queue.Queue()
        self.pending = deque()
        self.slots = [None] * MAX_VISIBLE
        self.live = {}                       # key -> _Banner, for remote dismissal
        self.ready = threading.Event()
        threading.Thread(target=self._run, name="macos-toast", daemon=True).start()
        self.ready.wait(timeout=5)

    def _run(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.screen_w = self.root.winfo_screenwidth()
        self.ready.set()
        self._pump()
        self.root.mainloop()

    def _pump(self):
        try:
            while True:
                kind, payload = self.inbox.get_nowait()
                if kind == "show":
                    self.pending.append(payload)
                elif kind == "dismiss":
                    banner = self.live.get(payload)
                    if banner is not None:
                        banner.dismiss()
                    else:
                        self.pending = deque(p for p in self.pending
                                             if p.get("key") != payload)
        except queue.Empty:
            pass

        while self.pending:
            slot = next((i for i, v in enumerate(self.slots) if v is None), None)
            if slot is None:
                break
            item = self.pending.popleft()
            try:
                self.slots[slot] = self._spawn(slot, item)
            except Exception as exc:
                self.slots[slot] = None
                print(f"  (banner failed: {exc})")

        self.root.after(80, self._pump)

    def _spawn(self, slot, item):
        final_x = self.screen_w - MARGIN - CARD_W - SHADOW_PAD
        y = MARGIN - SHADOW_PAD + slot * (CARD_H + GAP)
        composer = _Composer(item, final_x, y, self.screen_w)
        banner = _Banner(self, slot, composer, y, item)
        if item.get("key") is not None:
            self.live[item["key"]] = banner
        return banner

    def release(self, slot, key):
        self.slots[slot] = None
        if key is not None:
            self.live.pop(key, None)


_server = None
_server_lock = threading.Lock()


def _ensure_server():
    global _server
    with _server_lock:
        if _server is None:
            _server = _Server()
    return _server


def show_toast(app_name: str, title: str = "", body: str = "",
               bundle_id: str | None = None, actions=None,
               hold_ms: int | None = None, key=None,
               style: str | None = None) -> None:
    """
    Queue one macOS-style banner. Safe to call from any thread.

    actions: up to 2 tuples of (label, callback, kind) where kind is
             "positive" (green), "negative" (red) or "neutral" (blue).
             Callbacks run on the Tk thread - keep them non-blocking.
    style:   "call" for the macOS call banner (initials avatar + round handset
             buttons), None for the standard app notification layout.
    key:     an opaque id (e.g. the ANCS notification UID) so the banner can be
             pulled off screen later via dismiss_toast(key).
    """
    actions = order_actions((actions or [])[:2], style)
    _ensure_server().inbox.put(("show", {
        "app": app_name or "iPhone",
        "title": title or "",
        "body": body or "",
        "bundle_id": bundle_id,
        "actions": actions,
        "style": style,
        "hold_ms": hold_ms or (HOLD_ACTION_MS if actions else HOLD_MS),
        "key": key,
    }))


def dismiss_toast(key) -> None:
    """Pull a banner off screen early - the call was answered elsewhere, etc."""
    if key is None or _server is None:
        return
    _server.inbox.put(("dismiss", key))


# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    icons.prefetch(["net.whatsapp.WhatsApp"])

    show_toast("Phone", "Alex Whitfield", "", "com.apple.mobilephone",
               actions=[("Answer", lambda: print("answer"), "positive"),
                        ("Decline", lambda: print("decline"), "negative")],
               style="call", key=1234)
    time.sleep(0.6)
    show_toast("Phone", "+1 (740) 555-0190", "", "com.apple.mobilephone",
               actions=[("Answer", lambda: print("answer"), "positive"),
                        ("Decline", lambda: print("decline"), "negative")],
               style="call", key=5678)
    time.sleep(0.6)
    show_toast("WhatsApp", "Priya Sharma",
               "Something else happened I don't know exactly the steering was "
               "wobbly, some good bike mechanic is needed to fix that",
               "net.whatsapp.WhatsApp")
    time.sleep(0.6)
    show_toast("Messages", "Priya Sharma", "Reply from the banner?",
               "com.apple.MobileSMS",
               actions=[("Mark read", lambda: print("read"), "neutral")])

    time.sleep(6)
    print("simulating the call being answered on the phone")
    dismiss_toast(1234)
    time.sleep(8)
