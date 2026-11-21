"""Tests for the Pixoo64 word clock image (mediainfo/imaging/word_clock.py)."""

from __future__ import annotations

import datetime

import pytest

from mediainfo.imaging import word_clock as w


@pytest.mark.parametrize(
    "hour, minute, phrase, lines, extra",
    [
        (9, 40, "tjugo", ("TJUGO I", "TIO"), 0),
        (9, 40, "halv", ("TIO ÖVER HALV", "TIO"), 0),
        (9, 22, "tjugo", ("TJUGO ÖVER", "NIO"), 2),
        (12, 25, "tjugo", ("FEM I HALV", "ETT"), 0),
        (0, 15, "tjugo", ("KVART ÖVER", "TOLV"), 0),
        (3, 0, "tjugo", ("TRE",), 0),
        (13, 0, "tjugo", ("TRETTON",), 0),
        (19, 5, "tjugo", ("NITTON", "NOLL FEM"), 0),
        (23, 47, "halv", ("TJUGOTRE", "FYRTIOFEM"), 2),
    ],
)
def test_reads_the_time_like_the_web_clocks(hour, minute, phrase, lines, extra):
    reading = w.spoken_lines(hour, minute, phrase)
    assert reading.lines == lines
    assert reading.extra == extra
    assert reading.digital == (hour >= 13)


def test_classic_lines_wrap_to_fit_while_digital_keeps_the_hour_apart():
    assert w.display_lines(w.spoken_lines(9, 35)) == ["FEM ÖVER", "HALV TIO"]
    assert w.display_lines(w.spoken_lines(18, 35)) == ["ARTON", "TRETTIOFEM"]


@pytest.mark.parametrize("phrase", w.PHRASES)
def test_every_minute_fits_on_a_64_pixel_display(phrase):
    for hour in range(24):
        for minute in range(60):
            lines = w.display_lines(w.spoken_lines(hour, minute, phrase))
            assert 1 <= len(lines) <= 2
            assert all(w.text_width(line) <= 64 for line in lines), (hour, minute, lines)


def test_font_comes_from_the_shared_pixel_font_with_swedish_letters():
    glyphs = w._glyphs()
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZÅÄÖ ":
        assert len(glyphs[ch]) == 9
        assert all(len(row) == 5 for row in glyphs[ch])
    assert glyphs["Ä"][0] == ".#.#."


def test_render_draws_text_and_one_corner_dot_per_extra_minute():
    plain = w.render(w.spoken_lines(10, 20))
    assert plain.size == (64, 64)
    assert plain.getbbox() is not None
    assert plain.getpixel((1, 1)) == (0, 0, 0)

    dotted = w.render(w.spoken_lines(10, 23))
    corners = [(1, 1), (61, 1), (61, 61), (1, 61)]
    lit = [dotted.getpixel(c) != (0, 0, 0) for c in corners]
    assert lit == [True, True, True, False]


def test_render_now_uses_the_given_time():
    reading, image = w.render_now("tjugo", 64, datetime.datetime(2026, 11, 21, 14, 31))
    assert reading == w.Reading(("FJORTON", "TRETTIO"), 1, True)
    assert image.size == (64, 64)


def test_neon_glows_on_a_brick_wall():
    reading = w.spoken_lines(10, 23)
    neon = w.render(reading, 64, "neon")
    plain = w.render(reading, 64)
    assert neon.size == (64, 64)
    # The wall shows where the plain clock is black ...
    assert neon.getpixel((32, 1)) != (0, 0, 0)
    # ... the tubes glow around the letters, and the minute dots are drawn.
    x, y = next(
        (x, y)
        for y in range(64)
        for x in range(64)
        if plain.getpixel((x, y)) != (0, 0, 0) and 4 < x < 60 and 4 < y < 60
    )
    assert sum(neon.getpixel((x, y))) > sum(neon.getpixel((32, 1)))
    assert neon.getpixel((61, 1)) != neon.getpixel((1, 61))
