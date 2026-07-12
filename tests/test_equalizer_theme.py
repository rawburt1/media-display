"""Tests for the Equalizer theme (mediainfo/themes/equalizer.py)."""

from pathlib import Path

import pytest

from mediainfo.config.themes import EqualizerConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.equalizer import EqualizerTheme


def _music():
    return NowPlaying(source="kodi", media_type="music", title="Song", subtitle="Artist")


def _movie():
    return NowPlaying(source="kodi", media_type="movie", title="Alien")


def _artwork():
    return Artwork(url="https://example.com/art.jpg", label="Album art")


# ---------------------------------------------------------------------------
# prepare() - music-only gating, no real data needed
# ---------------------------------------------------------------------------


def test_music_reports_active():
    theme = EqualizerTheme()
    result = theme.prepare(_music(), _artwork(), Path("/x/abc.jpg"), None, None, EqualizerConfig())
    assert result.extra_payload == {"active": True}


def test_movie_returns_none():
    theme = EqualizerTheme()
    result = theme.prepare(
        _movie(), _artwork(), Path("/x/poster.jpg"), None, None, EqualizerConfig()
    )
    assert result is None


def test_episode_returns_none():
    theme = EqualizerTheme()
    now_playing = NowPlaying(source="kodi", media_type="episode", title="Breaking Bad")
    result = theme.prepare(
        now_playing, _artwork(), Path("/x/poster.jpg"), None, None, EqualizerConfig()
    )
    assert result is None


def test_idle_wallpaper_returns_none():
    theme = EqualizerTheme()
    now_playing = NowPlaying(source="idle", media_type="wallpaper", title="")
    result = theme.prepare(
        now_playing, _artwork(), Path("/x/art.jpg"), None, None, EqualizerConfig()
    )
    assert result is None


# ---------------------------------------------------------------------------
# client_assets()
# ---------------------------------------------------------------------------


def test_client_assets_registers_theme_handler():
    theme = EqualizerTheme()
    assets = theme.client_assets(EqualizerConfig())
    assert "window.themeHandlers.equalizer" in assets.js
    assert "theme-equalizer" in assets.css


@pytest.mark.parametrize("style", ["bars", "wave"])
def test_client_assets_includes_configured_style(style):
    theme = EqualizerTheme()
    assets = theme.client_assets(EqualizerConfig(style=style))
    assert f"style-{style}" in assets.js


def test_client_assets_falls_back_to_bars_for_invalid_style():
    theme = EqualizerTheme()
    assets = theme.client_assets(EqualizerConfig(style="nonsense; </script>"))
    assert "style-bars" in assets.js
    assert "nonsense" not in assets.js


@pytest.mark.parametrize("position", ["bottom", "top"])
def test_client_assets_includes_configured_position(position):
    theme = EqualizerTheme()
    assets = theme.client_assets(EqualizerConfig(position=position))
    assert f"position-{position}" in assets.js


def test_client_assets_falls_back_to_bottom_for_invalid_position():
    theme = EqualizerTheme()
    assets = theme.client_assets(EqualizerConfig(position="nonsense; </script>"))
    assert "position-bottom" in assets.js
    assert "nonsense" not in assets.js


def test_client_assets_uses_configured_bar_count():
    theme = EqualizerTheme()
    assets = theme.client_assets(EqualizerConfig(bar_count=8))
    assert "BAR_COUNT = 8" in assets.js


def test_client_assets_clamps_bar_count_to_range():
    theme = EqualizerTheme()
    assets_low = theme.client_assets(EqualizerConfig(bar_count=0))
    assert "BAR_COUNT = 1" in assets_low.js
    assets_high = theme.client_assets(EqualizerConfig(bar_count=999))
    assert "BAR_COUNT = 64" in assets_high.js


def test_client_assets_uses_configured_opacity():
    theme = EqualizerTheme()
    assets = theme.client_assets(EqualizerConfig(opacity=0.3))
    assert "#theme-equalizer.visible { opacity: 0.3; }" in assets.css


def test_client_assets_clamps_opacity_to_0_1_range():
    theme = EqualizerTheme()
    assets_low = theme.client_assets(EqualizerConfig(opacity=-1))
    assert "opacity: 0.0;" in assets_low.css
    assets_high = theme.client_assets(EqualizerConfig(opacity=5))
    assert "opacity: 1.0;" in assets_high.css


def test_wave_path_is_present_and_json_safe():
    theme = EqualizerTheme()
    assets = theme.client_assets(EqualizerConfig(style="wave"))
    assert "WAVE_PATH" in assets.js
    assert "M0.0," in assets.js
