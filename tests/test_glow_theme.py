"""Tests for the Glow theme (mediainfo/themes/glow.py)."""

from PIL import Image

from mediainfo.config.themes import GlowConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.glow import GlowTheme


def _solid_image(path, color=(200, 50, 50)):
    Image.new("RGB", (32, 32), color).save(path, format="PNG")
    return path


def _now_playing():
    return NowPlaying(source="kodi", media_type="music", title="Song", subtitle="Artist")


def _artwork():
    return Artwork(url="https://example.com/art.jpg", label="Album art")


# ---------------------------------------------------------------------------
# prepare()
# ---------------------------------------------------------------------------

def test_album_art_source_extracts_dominant_color(tmp_path):
    img_path = _solid_image(tmp_path / "art.png", (200, 50, 50))
    theme = GlowTheme()

    result = theme.prepare(
        _now_playing(), _artwork(), img_path, None, None, GlowConfig(color_source="album_art"),
    )

    assert result.extra_payload["color"] == "#c83232"


def test_fixed_source_uses_fixed_color_without_reading_image(tmp_path):
    theme = GlowTheme()
    result = theme.prepare(
        _now_playing(), _artwork(), tmp_path / "missing.jpg", None, None,
        GlowConfig(color_source="fixed", fixed_color="#112233"),
    )
    assert result.extra_payload["color"] == "#112233"


def test_album_art_source_returns_none_for_unreadable_image(tmp_path):
    theme = GlowTheme()
    result = theme.prepare(
        _now_playing(), _artwork(), tmp_path / "missing.jpg", None, None,
        GlowConfig(color_source="album_art"),
    )
    assert result is None


# ---------------------------------------------------------------------------
# client_assets()
# ---------------------------------------------------------------------------

def test_client_assets_registers_theme_handler():
    theme = GlowTheme()
    assets = theme.client_assets(GlowConfig())
    assert "window.themeHandlers.glow" in assets.js
    assert "theme-glow" in assets.css


def test_client_assets_includes_pulse_class_when_enabled():
    theme = GlowTheme()
    assets = theme.client_assets(GlowConfig(pulse=True))
    assert "theme-glow pulse" in assets.js


def test_client_assets_omits_pulse_class_when_disabled():
    theme = GlowTheme()
    assets = theme.client_assets(GlowConfig(pulse=False))
    assert "theme-glow pulse" not in assets.js
    assert "className = 'theme-glow'" in assets.js


def test_client_assets_clamps_intensity_above_one():
    theme = GlowTheme()
    assets = theme.client_assets(GlowConfig(intensity=5.0))
    assert "#theme-glow.visible { opacity: 1.0; }" in assets.css


def test_client_assets_clamps_negative_intensity():
    theme = GlowTheme()
    assets = theme.client_assets(GlowConfig(intensity=-3.0))
    assert "#theme-glow.visible { opacity: 0.0; }" in assets.css
