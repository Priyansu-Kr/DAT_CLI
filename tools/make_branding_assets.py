"""Regenerate DAT's branding assets from the source artwork.

The outputs are committed, so neither the install nor the GUI does any
image processing at startup:

    python3 tools/make_branding_assets.py --icon DAT_LOGO.png
    python3 tools/make_branding_assets.py --wordmark logo.png
    python3 tools/make_branding_assets.py --wordmark logo.png --icon DAT_LOGO.png

Two assets, because they are read at completely different sizes and each
flag rewrites only its own - regenerating the icon must not disturb the
wordmark:

* ``dat_wordmark.png`` - the full logo, shown ~22px tall inside the window
  where the name is legible, with its backdrop keyed out so it sits on the
  panel surface instead of pasting a coloured rectangle onto it.
* ``dat_icon.png`` / ``dat_icon.ico`` - a square mark for the taskbar/dock,
  read at 16-32px. Source artwork usually carries generous margins, so the
  mark is cropped to its own ink bounds and re-padded symmetrically; scaling
  the whole canvas instead would leave the mark tiny inside double padding.
"""
import argparse
import os
import sys
from typing import Optional, Tuple

from PIL import Image, ImageChops

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dat", "assets")

# How much of the icon tile the mark should occupy. Small icons get more:
# at 16px, padding is pixels that could have been the mark itself.
FILL_SMALL = 0.88
FILL_LARGE = 0.78

# Per-channel difference from the sampled backdrop that counts as ink,
# loose enough to ignore compression noise and a subtly uneven background.
INK_THRESHOLD = 24


def background_colour(image: Image.Image) -> Tuple[int, int, int, int]:
    """The artwork's own backdrop, sampled from a corner.

    Sampled rather than hardcoded so new artwork in different brand colours
    produces a matching icon without editing this file.
    """
    corner = image.convert("RGBA").getpixel((0, 0))
    if corner[3] == 0:
        return (0, 0, 0, 0)  # transparent artwork: keep the padding transparent
    return corner


def _has_transparency(image: Image.Image) -> bool:
    if image.mode not in ("RGBA", "LA", "PA") and "transparency" not in image.info:
        return False
    alpha = image.convert("RGBA").getchannel("A")
    return alpha.getextrema()[0] < 250


def ink_bbox(image: Image.Image) -> Optional[Tuple[int, int, int, int]]:
    """The bounds of the artwork itself, ignoring its margins.

    Transparency is the reliable signal when the artwork has it; otherwise
    "ink" is whatever differs from the backdrop colour. Colour distance
    rather than luminance, because a mark can be lighter *and* darker than
    its background - this logo's D is white and its T is blue.
    """
    rgba = image.convert("RGBA")
    if _has_transparency(image):
        mask = rgba.getchannel("A").point(lambda v: 255 if v > 10 else 0)
        return mask.getbbox()

    flat = Image.new("RGB", rgba.size, background_colour(image)[:3])
    diff = ImageChops.difference(rgba.convert("RGB"), flat)
    mask = diff.convert("L").point(lambda v: 255 if v > INK_THRESHOLD else 0)
    return mask.getbbox()


def transparent_wordmark(logo: Image.Image) -> Image.Image:
    """The wordmark with its backdrop removed, for use inside the dark UI.

    Keying the background out by colour match would leave a dark halo on the
    anti-aliased glyph edges, so for a light mark on a dark backdrop the
    alpha channel is derived from luminance instead: every pixel keeps the
    mark's colour and becomes transparent in proportion to how close it was
    to the background. Edges stay smooth.
    """
    rgba = logo.convert("RGBA")
    background = background_colour(logo)
    bg_luminance = 0.299 * background[0] + 0.587 * background[1] + 0.114 * background[2]

    if bg_luminance >= 128:
        # A dark mark on a light backdrop: invert the same reasoning.
        floor, ceiling, ink = 255.0, 0.0, (0, 0, 0)
    else:
        floor, ceiling, ink = bg_luminance, 255.0, (255, 255, 255)

    span = ceiling - floor or 1.0
    out = Image.new("RGBA", rgba.size, ink + (0,))
    source = rgba.load()
    target = out.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = source[x, y]
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            alpha = (luminance - floor) / span
            alpha = 0.0 if alpha < 0 else (1.0 if alpha > 1 else alpha)
            opacity = int(round(alpha * a))
            # The backdrop is not perfectly flat, which leaves background
            # pixels very slightly opaque - enough to defeat the crop below
            # and to grey the panel behind the mark.
            target[x, y] = ink + (opacity if opacity > 10 else 0,)

    bbox = out.getbbox()
    return out.crop(bbox) if bbox else out


def square_icon(source: Image.Image, size: int, recenter: bool = True) -> Image.Image:
    """A `size`x`size` icon built from `source`.

    With `recenter` off the source is only resized - the right treatment for
    artwork already exported as a square icon, whose padding is a deliberate
    part of the design and must not be second-guessed.
    """
    rgba = source.convert("RGBA")
    if not recenter:
        return rgba.resize((size, size), Image.LANCZOS)

    bbox = ink_bbox(source)
    mark = rgba.crop(bbox) if bbox else rgba

    fill = FILL_SMALL if size <= 32 else FILL_LARGE
    scale = (size * fill) / max(mark.width, mark.height)
    width = max(1, round(mark.width * scale))
    height = max(1, round(mark.height * scale))

    canvas = Image.new("RGBA", (size, size), background_colour(source))
    canvas.alpha_composite(
        mark.resize((width, height), Image.LANCZOS),
        ((size - width) // 2, (size - height) // 2),
    )
    return canvas


def write_wordmark(path: str) -> list:
    logo = Image.open(path)
    out = os.path.join(ASSETS_DIR, "dat_wordmark.png")
    transparent_wordmark(logo).save(out)
    return [out]


def write_icon(path: str) -> list:
    source = Image.open(path)
    ratio = source.width / source.height
    # A tolerance rather than an exact match: a hand-exported mark is often
    # a pixel or two off square, which should not change how it is treated.
    prepared_square = 0.95 <= ratio <= 1.05

    bbox = ink_bbox(source)
    if bbox:
        coverage = max(
            (bbox[2] - bbox[0]) / source.width, (bbox[3] - bbox[1]) / source.height
        )
        # Square *and* tightly cropped means it was exported as an icon.
        # Square with wide margins still wants re-centering, or the mark
        # ends up padded twice and unreadable at 16px.
        prepared_square = prepared_square and coverage > 0.9

    png = os.path.join(ASSETS_DIR, "dat_icon.png")
    ico = os.path.join(ASSETS_DIR, "dat_icon.ico")
    master = square_icon(source, 256, recenter=not prepared_square)
    master.save(png)
    # Windows selects the exact size it needs from inside the .ico rather
    # than resampling one image, so every size is written into the file.
    master.save(ico, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    return [png, ico]


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate DAT's branding assets. Each flag rewrites only its own asset.",
    )
    parser.add_argument("--wordmark", metavar="FILE", help="Source logo for the in-window wordmark")
    parser.add_argument("--icon", metavar="FILE", help="Source artwork for the taskbar/dock icon")
    args = parser.parse_args(argv)

    if not args.wordmark and not args.icon:
        parser.error("nothing to do - pass --wordmark and/or --icon")

    for label, path in (("wordmark", args.wordmark), ("icon", args.icon)):
        if path and not os.path.isfile(path):
            print(f"No such {label} source: {path}")
            return 1

    os.makedirs(ASSETS_DIR, exist_ok=True)
    written = []
    if args.wordmark:
        written += write_wordmark(args.wordmark)
    if args.icon:
        written += write_icon(args.icon)

    for path in written:
        print(f"wrote {path} ({os.path.getsize(path)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())