"""Tests for the Ken Burns theme (mediainfo/themes/ken_burns.py)."""

from pathlib import Path

from mediainfo.config.themes import KenBurnsConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.ken_burns import KenBurnsTheme


def _now_playing():
    return NowPlaying(source="kodi", media_type="music", title="Song", subtitle="Artist")


def _artwork():
    return Artwork(url="https://example.com/art.jpg", label="Album art")


# ---------------------------------------------------------------------------
# prepare()
# ---------------------------------------------------------------------------


def test_prepare_echoes_back_image_url():
    theme = KenBurnsTheme()
    image_path = Path("/some/dir/abc123.jpg")

    result = theme.prepare(_now_playing(), _artwork(), image_path, None, None, KenBurnsConfig())

    assert result.extra_payload["image"] == "/image/current?v=abc123"


# ---------------------------------------------------------------------------
# client_assets()
# ---------------------------------------------------------------------------


def test_client_assets_registers_theme_handler():
    theme = KenBurnsTheme()
    assets = theme.client_assets(KenBurnsConfig())
    assert "window.themeHandlers.ken_burns" in assets.js
    assert "theme-ken-burns" in assets.css


def test_client_assets_includes_all_variants():
    theme = KenBurnsTheme()
    assets = theme.client_assets(KenBurnsConfig())
    assert "kb-zoom-in" in assets.js
    assert "kb-zoom-out" in assets.js
    assert "kb-pan" in assets.js
    assert "kb-zoom-in" in assets.css
    assert "kb-zoom-out" in assets.css
    assert "kb-pan" in assets.css


def test_client_assets_uses_configured_duration():
    theme = KenBurnsTheme()
    assets = theme.client_assets(KenBurnsConfig(duration_seconds=45))
    assert "45s" in assets.css


def test_client_assets_clamps_duration_to_at_least_one_second():
    theme = KenBurnsTheme()
    assets = theme.client_assets(KenBurnsConfig(duration_seconds=0))
    assert "1s" in assets.css
    assert "0s" not in assets.css


def test_client_assets_clamps_opacity_above_one():
    theme = KenBurnsTheme()
    assets = theme.client_assets(KenBurnsConfig(opacity=3.0))
    assert "#theme-ken-burns.visible { opacity: 1.0; }" in assets.css


def test_client_assets_clamps_negative_opacity():
    theme = KenBurnsTheme()
    assets = theme.client_assets(KenBurnsConfig(opacity=-1.0))
    assert "#theme-ken-burns.visible { opacity: 0.0; }" in assets.css
