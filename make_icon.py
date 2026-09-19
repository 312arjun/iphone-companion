"""
make_icon.py - turn the brand artwork into the app's icon assets.

You do NOT need this to run or build the app. Both outputs below are
committed, and appicon.py reads them straight from assets/. This is the
authoring tool that produced them, kept so the assets are reproducible and
so anyone rebranding a fork can regenerate them:

    python make_icon.py "path\\to\\iphone-companion.png"

It writes:
    assets/app_icon.png   1024px master, cropped to the artwork's own bounds
    assets/app.ico        multi-resolution 16 -> 256, for the exe, the window
                          and the installer

The source already carries an alpha channel with rounded corners, so this
crops to the alpha bounding box rather than trying to key out a background -
keying white would have eaten the phone outline, which is also white.

Downsampling is done in two stages through LANCZOS. A single jump from 1254px
to 16px loses the Windows flag entirely; halving first keeps it legible.
"""

from __future__ import annotations

import os
import sys

from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
MASTER = os.path.join(ASSETS, "app_icon.png")
ICO = os.path.join(ASSETS, "app.ico")

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
MASTER_SIZE = 1024
PAD_RATIO = 0.0          # artwork already has its own breathing room


def load_and_crop(path: str) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    box = image.getchannel("A").getbbox()
    if box is None:
        raise SystemExit("that image is fully transparent")
    image = image.crop(box)

    # square it off, centred, so no resize ever distorts the artwork
    side = max(image.size)
    if PAD_RATIO:
        side = int(side * (1 + PAD_RATIO * 2))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(image, ((side - image.width) // 2,
                                   (side - image.height) // 2))
    return canvas


def downscale(image: Image.Image, size: int) -> Image.Image:
    """Halve repeatedly before the final step, or small sizes turn to mush."""
    current = image
    while current.width // 2 > size:
        current = current.resize((current.width // 2, current.height // 2),
                                 Image.LANCZOS)
    return current.resize((size, size), Image.LANCZOS)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(
            'usage: python make_icon.py "path\\to\\icon.png"')
    source = sys.argv[1]
    if not os.path.exists(source):
        raise SystemExit(f"not found: {source}")

    os.makedirs(ASSETS, exist_ok=True)
    art = load_and_crop(source)
    print(f"cropped to {art.size[0]}x{art.size[1]}")

    downscale(art, MASTER_SIZE).save(MASTER)
    print(f"wrote {MASTER}")

    frames = [downscale(art, size) for size in ICO_SIZES]
    frames[-1].save(ICO, format="ICO",
                    sizes=[(size, size) for size in ICO_SIZES])
    print(f"wrote {ICO}  ({', '.join(str(s) for s in ICO_SIZES)})")


if __name__ == "__main__":
    main()
