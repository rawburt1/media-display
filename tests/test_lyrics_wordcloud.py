from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from mediainfo.imaging.colors import dominant_colors
from mediainfo.imaging.lyrics_wordcloud import (
    _palette_color_func,
    generate,
    strip_lrc_timestamps,
)

_LYRICS = """\
[00:01.00] Davy's on the road again
[00:04.00] Wearin' different clothes again
[00:07.00] Davy's turning handouts down
[00:10.00] To keep his pockets clean
[00:13.00] All his goods are sold again
[00:16.00] His word's as good as gold again
[00:19.00] Sez if you see Jean now ask her
[00:22.00] Please to pity me
"""


def _half_and_half_image(width: int = 64, height: int = 64) -> Image.Image:
    """Left half pure red, right half pure blue - gives _dominant_colors
    an unambiguous, predictable palette to extract."""
    img = Image.new("RGB", (width, height), (255, 0, 0))
    for x in range(width // 2, width):
        for y in range(height):
            img.putpixel((x, y), (0, 0, 255))
    return img


def _album_art(tmp_path: Path) -> Path:
    path = tmp_path / "albumart.jpg"
    _half_and_half_image().save(path)
    return path


def _has_visible_pixels(png_path: Path) -> bool:
    """True if the rendered word cloud actually drew something (a
    non-fully-transparent pixel) - a coarse but effective way to catch a
    generate() that silently produced a blank image."""
    img = Image.open(png_path).convert("RGBA")
    alpha = np.array(img)[:, :, 3]
    return bool((alpha > 0).any())


def test_strip_lrc_timestamps_drops_timestamps():
    assert strip_lrc_timestamps("[00:01.00] hello world") == "hello world"


def test_strip_lrc_timestamps_keeps_untimestamped_lines():
    assert strip_lrc_timestamps("plain lyrics\nno timestamps here") == (
        "plain lyrics\nno timestamps here"
    )


def test_strip_lrc_timestamps_drops_blank_lines():
    result = strip_lrc_timestamps("[00:01.00] first\n\n[00:02.00] second")
    assert result == "first\nsecond"


def test_palette_color_func_only_returns_given_colors():
    colors = [(255, 0, 0), (0, 0, 255)]
    color_func = _palette_color_func(colors)
    rnd = np.random.RandomState(0)
    for _ in range(20):
        result = color_func(random_state=rnd)
        assert result in ("rgb(255, 0, 0)", "rgb(0, 0, 255)")


def test_generate_without_mask_writes_valid_image(tmp_path):
    out_path = tmp_path / "wordcloud.png"
    generate(_LYRICS, _album_art(tmp_path), out_path, use_mask=False, width=200, height=200)

    assert out_path.exists()
    img = Image.open(out_path)
    assert img.size == (200, 200)
    assert _has_visible_pixels(out_path)


def test_generate_with_mask_writes_valid_image(tmp_path):
    out_path = tmp_path / "wordcloud.png"
    generate(_LYRICS, _album_art(tmp_path), out_path, use_mask=True, width=200, height=200)

    assert out_path.exists()
    img = Image.open(out_path)
    assert img.size == (200, 200)
    assert _has_visible_pixels(out_path)


def test_generate_output_has_transparent_background(tmp_path):
    """Not every pixel should be opaque - a solid-background render would
    defeat the point of using mode=RGBA/background_color=None to match
    the web output's own dark page background."""
    out_path = tmp_path / "wordcloud.png"
    generate(_LYRICS, _album_art(tmp_path), out_path, use_mask=False, width=200, height=200)

    alpha = np.array(Image.open(out_path).convert("RGBA"))[:, :, 3]
    assert (alpha == 0).any()


def test_generate_raises_for_missing_album_art(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate(_LYRICS, tmp_path / "missing.jpg", tmp_path / "out.png", use_mask=False)


# ---------------------------------------------------------------------------
# Real-world example: Manfred Mann's Earth Band - "Davy's on the Road Again"
# (from the album Watch) - full real lyrics and real album art, rather than
# the synthetic fixtures above, as a concrete sanity check that generate()
# holds up on an actual .lrc file and actual (photographic, not flat-color)
# artwork - see tests/fixtures/lyrics_wordcloud/.
# ---------------------------------------------------------------------------

_REAL_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "lyrics_wordcloud"
_REAL_LRC_PATH = _REAL_FIXTURES_DIR / "davys_on_the_road_again.lrc"
_REAL_ALBUM_ART_PATH = _REAL_FIXTURES_DIR / "watch_albumart.jpg"


def test_generate_real_example_without_mask_writes_valid_image(tmp_path):
    out_path = tmp_path / "wordcloud.png"
    generate(
        _REAL_LRC_PATH.read_text(encoding="utf-8"),
        _REAL_ALBUM_ART_PATH,
        out_path,
        use_mask=False,
        width=400,
        height=400,
    )

    assert out_path.exists()
    img = Image.open(out_path)
    assert img.size == (400, 400)
    assert _has_visible_pixels(out_path)


def test_generate_real_example_with_mask_writes_valid_image(tmp_path):
    out_path = tmp_path / "wordcloud.png"
    generate(
        _REAL_LRC_PATH.read_text(encoding="utf-8"),
        _REAL_ALBUM_ART_PATH,
        out_path,
        use_mask=True,
        width=400,
        height=400,
    )

    assert out_path.exists()
    img = Image.open(out_path)
    assert img.size == (400, 400)
    assert _has_visible_pixels(out_path)


def test_generate_real_example_uses_album_art_palette(tmp_path):
    """The rendered colors should come from the album art's own dominant
    palette (sky blue / white cloud / sandy tan / warm brown-grey), not
    some unrelated default - a coarse check that dominant_colors() is
    actually driving color_func rather than e.g. matplotlib's default
    qualitative colormap sneaking in."""
    out_path = tmp_path / "wordcloud.png"
    generate(
        _REAL_LRC_PATH.read_text(encoding="utf-8"),
        _REAL_ALBUM_ART_PATH,
        out_path,
        use_mask=False,
        width=400,
        height=400,
    )

    album_colors = set(dominant_colors(Image.open(_REAL_ALBUM_ART_PATH), count=8))
    rendered = np.array(Image.open(out_path).convert("RGBA"))
    opaque_pixels = rendered[rendered[:, :, 3] > 0][:, :3]
    rendered_colors = {tuple(c) for c in np.unique(opaque_pixels, axis=0).tolist()}

    assert rendered_colors & album_colors, (
        "expected at least one rendered pixel color to exactly match one of "
        "the album art's own dominant colors"
    )
