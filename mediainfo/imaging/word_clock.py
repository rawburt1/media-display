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

from PIL import Image

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


def render(reading: Reading, size: int = 64) -> Image.Image:
    """Draw "KLOCKAN ÄR" and the time's lines centered, with the minutes past
    the 5-minute step as 1-4 dots in the corners, like a classic word clock."""
    img = Image.new("RGB", (size, size), (0, 0, 0))
    lines = [(_HEADER, _HEADER_COLOR)] + [
        (line, _TIME_COLOR) for line in display_lines(reading, size)
    ]
    # Spread the lines over the height, but keep them together as one text.
    gap = min(9, (size - 12 - len(lines) * _GLYPH_H) // max(1, len(lines) - 1))
    block = len(lines) * _GLYPH_H + (len(lines) - 1) * gap
    y = (size - block) // 2
    for text, color in lines:
        _draw_text(img, text, (size - text_width(text)) // 2, y, color)
        y += _GLYPH_H + gap
    # Corner dots clockwise from the top left: 1 = top left, 2 = + top right ...
    corners = [(1, 1), (size - 3, 1), (size - 3, size - 3), (1, size - 3)]
    for cx, cy in corners[: reading.extra]:
        for dx in range(2):
            for dy in range(2):
                img.putpixel((cx + dx, cy + dy), _TIME_COLOR)
    return img


def render_now(
    phrase: str = "tjugo", size: int = 64, now: Optional[datetime.datetime] = None
) -> Tuple[Reading, Image.Image]:
    now = now or datetime.datetime.now()
    reading = spoken_lines(now.hour, now.minute, phrase)
    return reading, render(reading, size)
