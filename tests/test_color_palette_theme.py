"""Tests for the Color Palette theme (mediainfo/themes/color_palette.py)."""

from unittest.mock import MagicMock

import pytest
from PIL import Image

from mediainfo.config.themes import ColorPaletteConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.color_palette import ColorPaletteTheme


def _half_and_half_image(path, width=64, height=64):
    # PNG (lossless) - a lossy JPEG would drift the exact (255, 0, 0)/
    # (0, 0, 255) values this test asserts on by a few units.
    img = Image.new("RGB", (width, height), (255, 0, 0))
    for x in range(width // 2, width):
        for y in range(height):
            img.putpixel((x, y), (0, 0, 255))
    img.save(path, format="PNG")
    return path


def _now_playing():
    return NowPlaying(source="kodi", media_type="music", title="Song", subtitle="Artist")


def _artwork():
    return Artwork(url="https://example.com/art.jpg", label="Album art")


# ---------------------------------------------------------------------------
# prepare()
# ---------------------------------------------------------------------------

def test_prepare_returns_hex_colors(tmp_path):
    img_path = _half_and_half_image(tmp_path / "art.png")
    theme = ColorPaletteTheme()

    result = theme.prepare(
        _now_playing(), _artwork(), img_path, MagicMock(), None, ColorPaletteConfig(swatch_count=2),
    )

    assert result is not None
    assert "#ff0000" in result.extra_payload["colors"]
    assert "#0000ff" in result.extra_payload["colors"]


def test_prepare_respects_swatch_count(tmp_path):
    img_path = tmp_path / "art.jpg"
    img = Image.new("RGB", (64, 64), (0, 0, 0))
    for x in range(64):
        for y in range(64):
            img.putpixel((x, y), (x % 8 * 30, y % 8 * 30, (x + y) % 8 * 30))
    img.save(img_path)
    theme = ColorPaletteTheme()

    result = theme.prepare(
        _now_playing(), _artwork(), img_path, MagicMock(), None, ColorPaletteConfig(swatch_count=3),
    )

    assert len(result.extra_payload["colors"]) <= 3


def test_prepare_returns_none_for_unreadable_image(tmp_path):
    theme = ColorPaletteTheme()
    result = theme.prepare(
        _now_playing(), _artwork(), tmp_path / "missing.jpg", MagicMock(), None, ColorPaletteConfig(),
    )
    assert result is None


# ---------------------------------------------------------------------------
# client_assets()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("position", ["bottom", "top", "side"])
def test_client_assets_includes_configured_position(position):
    theme = ColorPaletteTheme()
    assets = theme.client_assets(ColorPaletteConfig(swatch_position=position))
    assert f"position-{position}" in assets.js


def test_client_assets_falls_back_to_bottom_for_invalid_position():
    theme = ColorPaletteTheme()
    assets = theme.client_assets(ColorPaletteConfig(swatch_position="nonsense; </script>"))
    assert "position-bottom" in assets.js
    assert "nonsense" not in assets.js


def test_client_assets_registers_theme_handler():
    theme = ColorPaletteTheme()
    assets = theme.client_assets(ColorPaletteConfig())
    assert "window.themeHandlers.color_palette" in assets.js
