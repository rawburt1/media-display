"""The Swedish word clock drawn as a small LED image (the Pixoo64's idle clock).

Reads the time exactly like the web word clocks (mediainfo/outputs/static/
ordklocka/tid.js): 00:00-12:59 the classic way ("fem i halv ett") with
12-hour names, from 13:00 digitally ("arton tjugofem"), in 5-minute steps
with the minutes beyond shown as up to four dots. The letters use the same
5x7 dot font as the bus sign and domino clocks, parsed from pixelfont.js so
there is only one copy of it.
"""

from __future__ import annotations

import datetime
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

from PIL import Image, ImageChops, ImageEnhance, ImageFilter

_FONT_JS = (
    Path(__file__).resolve().parent.parent / "outputs" / "static" / "ordklocka" / "pixelfont.js"
)

# Hour words 0-23. Hour 0 reads "tolv" (kvart över tolv).
_HOUR_WORDS: List[List[str]] = [
    ["TOLV"], ["ETT"], ["TVÅ"], ["TRE"], ["FYRA"], ["FEM"], ["SEX"], ["SJU"],
    ["ÅTTA"], ["NIO"], ["TIO"], ["ELVA"], ["TOLV"], ["TRETTON"], ["FJORTON"],
    ["FEMTON"], ["SEXTON"], ["SJUTTON"], ["ARTON"], ["NITTON"], ["TJUGO"],
    ["TJUGO", "ETT"], ["TJUGO", "TVÅ"], ["TJUGO", "TRE"],
]  # fmt: skip

# Digital reading, one inner list per spoken word.
_DIGITAL_MINUTES: Dict[int, List[List[str]]] = {
    0: [], 5: [["NOLL"], ["FEM"]], 10: [["TIO"]], 15: [["FEMTON"]],
    20: [["TJUGO"]], 25: [["TJUGO", "FEM"]], 30: [["TRETTIO"]],
    35: [["TRETTIO", "FEM"]], 40: [["FYRTIO"]], 45: [["FYRTIO", "FEM"]],
    50: [["FEMTIO"]], 55: [["FEMTIO", "FEM"]],
}  # fmt: skip

# Accepted phrasings: "tjugo" says "tjugo över"/"tjugo i" at :20/:40,
# "halv" says "tio i halv"/"tio över halv" (the web clocks' 20/40 toggle).
PHRASES = ("tjugo", "halv")


def _classic_phrase(m5: int, phrase: str) -> Tuple[List[str], int]:
    """Minute words for the classic reading and whether they refer to the next hour."""
    if m5 == 20 and phrase == "halv":
        return ["TIO", "I", "HALV"], 1
    if m5 == 40 and phrase == "halv":
        return ["TIO", "ÖVER", "HALV"], 1
    return {
        0: ([], 0),
        5: (["FEM", "ÖVER"], 0),
        10: (["TIO", "ÖVER"], 0),
        15: (["KVART", "ÖVER"], 0),
        20: (["TJUGO", "ÖVER"], 0),
        25: (["FEM", "I", "HALV"], 1),
        30: (["HALV"], 1),
        35: (["FEM", "ÖVER", "HALV"], 1),
        40: (["TJUGO", "I"], 1),
        45: (["KVART", "I"], 1),
        50: (["TIO", "I"], 1),
        55: (["FEM", "I"], 1),
    }[m5]


class Reading(NamedTuple):
    """What the clock says: the lines after "KLOCKAN ÄR", plus 0-4 extra minutes."""

    lines: Tuple[str, ...]
    extra: int
    digital: bool = False


def spoken_lines(hour: int, minute: int, phrase: str = "tjugo") -> Reading:
    """The lines shown after "KLOCKAN ÄR", like sida.js's lines():
    classic ("FEM I HALV", "TRE"), digital ("FJORTON", "TJUGOFEM")."""
    m5 = minute - minute % 5
    extra = minute % 5
    if hour >= 13:
        hour_word = "".join(_HOUR_WORDS[hour])
        minutes = " ".join("".join(parts) for parts in _DIGITAL_MINUTES[m5])
        return Reading((hour_word, minutes) if minutes else (hour_word,), extra, True)
    minute_words, bump = _classic_phrase(m5, phrase)
    hour_word = "".join(_HOUR_WORDS[(hour + bump) % 12])
    if minute_words:
        return Reading((" ".join(minute_words), hour_word), extra)
    return Reading((hour_word,), extra)


@lru_cache(maxsize=1)
def _glyphs() -> Dict[str, List[str]]:
    """pixelfont.js's glyphs, 9 rows each: two rows for dots/ring, then 7 rows of letter."""
    source = _FONT_JS.read_text(encoding="utf-8")
    base = {ch: s.split("|") for ch, s in re.findall(r'"?([A-Z0-9:+.\- ])"?: "([.#|]+)"', source)}
    blank = ["....."] * 2
    glyphs = {ch: blank + rows for ch, rows in base.items()}
    glyphs["Ä"] = [".#.#.", "....."] + base["A"]
    glyphs["Ö"] = [".#.#.", "....."] + base["O"]
    glyphs["Å"] = ["..#..", ".#.#.", "..#..", ".###.", "#...#", "#...#", "#####", "#...#", "#...#"]
    return glyphs


_GLYPH_W, _GLYPH_H, _ADVANCE = 5, 9, 6
_HEADER = "KLOCKAN ÄR"
# Warm white on black; the header is dimmer so the time stands out.
_HEADER_COLOR = (150, 110, 60)
_TIME_COLOR = (255, 196, 110)


def _draw_text(img: Image.Image, text: str, x: int, y: int, color: Tuple[int, int, int]) -> None:
    glyphs = _glyphs()
    pixels = img.load()
    assert pixels is not None
    for i, ch in enumerate(text):
        rows = glyphs.get(ch, glyphs[" "])
        for dy, row in enumerate(rows):
            for dx, bit in enumerate(row):
                px, py = x + i * _ADVANCE + dx, y + dy
                if bit == "#" and 0 <= px < img.width and 0 <= py < img.height:
                    pixels[px, py] = color


def text_width(text: str) -> int:
    return len(text) * _ADVANCE - 1


def display_lines(reading: Reading, size: int = 64) -> List[str]:
    """The time's lines as they fit across the display. Digital readings keep
    the hour on its own line ("TJUGOTRE" / "FYRTIOFEM"); classic ones are
    wrapped word by word, so "FEM ÖVER HALV TOLV" becomes "FEM ÖVER" / "HALV TOLV"."""
    if reading.digital:
        return list(reading.lines)
    lines: List[str] = []
    for word in " ".join(reading.lines).split():
        if lines and text_width(f"{lines[-1]} {word}") <= size:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines


Color = Tuple[int, int, int]

# Looks for the clock: "plain" (warm white on black) and "neon" (glowing
# tubes on a dark brick wall, like /ordklocka/neon).
THEMES = ("plain", "neon")

# Neon tube colors, same as neon.html's default theme.
_NEON_HEADER = (63, 240, 255)
_NEON_TIME = (255, 79, 216)


def _layout(reading: Reading, size: int) -> List[Tuple[str, int, int, bool]]:
    """(text, x, y, is_header) for "KLOCKAN ÄR" and the time's lines,
    centered and spread over the height but kept together as one text."""
    lines = [_HEADER] + display_lines(reading, size)
    gap = min(9, (size - 12 - len(lines) * _GLYPH_H) // max(1, len(lines) - 1))
    block = len(lines) * _GLYPH_H + (len(lines) - 1) * gap
    y = (size - block) // 2
    placed = []
    for i, text in enumerate(lines):
        placed.append((text, (size - text_width(text)) // 2, y, i == 0))
        y += _GLYPH_H + gap
    return placed


def _corner_dots(img: Image.Image, extra: int, color: Color) -> None:
    """Minutes past the 5-minute step as 2x2 dots in the corners, clockwise
    from the top left, like a classic word clock."""
    size = img.width
    corners = [(1, 1), (size - 3, 1), (size - 3, size - 3), (1, size - 3)]
    for cx, cy in corners[:extra]:
        for dx in range(2):
            for dy in range(2):
                img.putpixel((cx + dx, cy + dy), color)


def _draw(reading: Reading, img: Image.Image, header: Color, time: Color) -> None:
    for text, x, y, is_header in _layout(reading, img.width):
        _draw_text(img, text, x, y, header if is_header else time)
    _corner_dots(img, reading.extra, time)


def _mix_white(color: Color, amount: float) -> Color:
    r, g, b = color
    return (
        round(r * amount + 255 * (1 - amount)),
        round(g * amount + 255 * (1 - amount)),
        round(b * amount + 255 * (1 - amount)),
    )


def _brick_wall(size: int) -> Image.Image:
    """A very dark brick wall: 4-pixel courses with offset joints."""
    img = Image.new("RGB", (size, size), (26, 12, 10))
    pixels = img.load()
    assert pixels is not None
    for y in range(size):
        course, row = divmod(y, 4)
        for x in range(size):
            joint = (x + (4 if course % 2 else 0)) % 8 == 0
            if row == 3 or joint:
                pixels[x, y] = (8, 4, 4)
            elif (x * 7 + course * 13) % 11 == 0:
                pixels[x, y] = (32, 15, 12)  # a little texture in the brick
    return img


def _render_neon(reading: Reading, size: int) -> Image.Image:
    # The glow: the tubes in full color, blurred and added onto the wall.
    tubes = Image.new("RGB", (size, size))
    _draw(reading, tubes, _NEON_HEADER, _NEON_TIME)
    glow = tubes.filter(ImageFilter.GaussianBlur(1.6))
    glow = ImageEnhance.Brightness(glow).enhance(1.8)
    img = ImageChops.add(_brick_wall(size), glow)
    # The tubes themselves: almost white-hot, tinted by their gas.
    core = Image.new("RGB", (size, size))
    _draw(reading, core, _mix_white(_NEON_HEADER, 0.45), _mix_white(_NEON_TIME, 0.45))
    img.paste(core, mask=core.convert("L").point(lambda v: 255 if v else 0))
    return img


def render(reading: Reading, size: int = 64, theme: str = "plain") -> Image.Image:
    """Draw "KLOCKAN ÄR" and the time's lines centered, with the minutes past
    the 5-minute step as 1-4 dots in the corners."""
    if theme == "neon":
        return _render_neon(reading, size)
    img = Image.new("RGB", (size, size), (0, 0, 0))
    _draw(reading, img, _HEADER_COLOR, _TIME_COLOR)
    return img


def render_now(
    phrase: str = "tjugo",
    size: int = 64,
    now: Optional[datetime.datetime] = None,
    theme: str = "plain",
) -> Tuple[Reading, Image.Image]:
    now = now or datetime.datetime.now()
    reading = spoken_lines(now.hour, now.minute, phrase)
    return reading, render(reading, size, theme)
