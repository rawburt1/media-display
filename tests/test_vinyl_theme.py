"""Tests for the Vinyl theme (mediainfo/themes/vinyl.py)."""

from pathlib import Path

import pytest

from mediainfo.config.themes import VinylThemeConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.vinyl import VinylTheme


def _music():
    return NowPlaying(source="kodi", media_type="music", title="Song", subtitle="Artist")


def _movie():
    return NowPlaying(source="kodi", media_type="movie", title="Alien")


def _artwork():
    return Artwork(url="https://example.com/art.jpg", label="Album art")


# ---------------------------------------------------------------------------
# prepare() - music-only gating
# ---------------------------------------------------------------------------


def test_music_echoes_back_image_url():
    theme = VinylTheme()
    image_path = Path("/some/dir/abc123.jpg")

    result = theme.prepare(_music(), _artwork(), image_path, None, None, VinylThemeConfig())

    assert result.extra_payload["image"] == "/image/current?v=abc123"


def test_movie_returns_none():
    theme = VinylTheme()
    result = theme.prepare(
        _movie(),
        _artwork(),
        Path("/some/poster.jpg"),
        None,
        None,
        VinylThemeConfig(),
    )
    assert result is None


def test_episode_returns_none():
    theme = VinylTheme()
    now_playing = NowPlaying(source="kodi", media_type="episode", title="Breaking Bad")
    result = theme.prepare(
        now_playing,
        _artwork(),
        Path("/some/poster.jpg"),
        None,
        None,
        VinylThemeConfig(),
    )
    assert result is None


def test_idle_wallpaper_returns_none():
    theme = VinylTheme()
    now_playing = NowPlaying(source="idle", media_type="wallpaper", title="")
    result = theme.prepare(
        now_playing,
        _artwork(),
        Path("/some/art.jpg"),
        None,
        None,
        VinylThemeConfig(),
    )
    assert result is None


# ---------------------------------------------------------------------------
# client_assets()
# ---------------------------------------------------------------------------


def test_client_assets_registers_theme_handler():
    theme = VinylTheme()
    assets = theme.client_assets(VinylThemeConfig())
    assert "window.themeHandlers.vinyl" in assets.js
    assert "theme-vinyl" in assets.css


@pytest.mark.parametrize(
    "corner", ["bottom-right", "bottom-left", "top-right", "top-left", "center"]
)
def test_client_assets_includes_configured_corner(corner):
    theme = VinylTheme()
    assets = theme.client_assets(VinylThemeConfig(corner=corner))
    assert f"corner-{corner}" in assets.js


def test_client_assets_falls_back_to_bottom_left_for_invalid_corner():
    theme = VinylTheme()
    assets = theme.client_assets(VinylThemeConfig(corner="nonsense; </script>"))
    assert "corner-bottom-left" in assets.js
    assert "nonsense" not in assets.js


def test_client_assets_uses_configured_rotation_seconds():
    theme = VinylTheme()
    assets = theme.client_assets(VinylThemeConfig(rotation_seconds=12))
    assert "theme-vinyl-spin 12s" in assets.css


def test_client_assets_clamps_rotation_seconds_to_at_least_one():
    theme = VinylTheme()
    assets = theme.client_assets(VinylThemeConfig(rotation_seconds=0))
    assert "theme-vinyl-spin 1s" in assets.css
    assert "theme-vinyl-spin 0s" not in assets.css


def test_client_assets_uses_configured_size():
    theme = VinylTheme()
    assets = theme.client_assets(VinylThemeConfig(size_vmin=55))
    assert "width: 55vmin; height: 55vmin;" in assets.css
