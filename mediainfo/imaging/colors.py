"""Shared color-extraction helpers.

Promoted out of mediainfo/lyrics_wordcloud.py (its first caller, via
_palette_color_func) so other consumers - the Display Themes system's
Color Palette/Glow/Blurred Background themes in particular - can share
one implementation instead of each re-deriving a palette from artwork.
"""

from __future__ import annotations

from typing import List, Tuple, cast

from PIL import Image


def dominant_colors(image: Image.Image, count: int = 8) -> List[Tuple[int, int, int]]:
    """The `count` most common colors in `image`, most-prevalent first.
    Quantizes to a small adaptive palette first so near-duplicate shades
    of the same color collapse into one entry, rather than every one of a
    photo's thousands of distinct pixel colors competing separately."""
    quantized = image.convert("RGB").quantize(colors=count)
    palette = quantized.getpalette() or []
    counts = sorted(quantized.getcolors() or [], reverse=True)
    colors = []
    for _, index in counts:
        offset = cast(int, index) * 3
        r, g, b = palette[offset : offset + 3]
        colors.append((r, g, b))
    return colors


def to_hex(rgb: Tuple[int, int, int]) -> str:
    """(r, g, b) -> "#rrggbb", for pushing a color to CSS-facing JSON."""
    return "#{:02x}{:02x}{:02x}".format(*rgb)
