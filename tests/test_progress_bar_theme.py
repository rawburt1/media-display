"""Tests for the Now Playing Progress theme (mediainfo/themes/progress_bar.py)."""

import pytest

from mediainfo.config.themes import ProgressBarConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.progress_bar import ProgressBarTheme


def _artwork():
    return Artwork(url="https://example.com/art.jpg", label="Album art")


def _now_playing(media_type="music", position=None, duration=None):
    np = NowPlaying(source="kodi", media_type=media_type, title="X", subtitle="Y")
    np.position_seconds = position
    np.duration_seconds = duration
    return np


# ---------------------------------------------------------------------------
# prepare() - media-type-agnostic, gated only on position/duration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("media_type", ["music", "movie", "episode"])
def test_reports_position_and_duration_for_any_media_type(media_type):
    theme = ProgressBarTheme()
    now_playing = _now_playing(media_type=media_type, position=42.5, duration=180.0)

    result = theme.prepare(now_playing, _artwork(), None, None, None, ProgressBarConfig())

    assert result.extra_payload["position_seconds"] == 42.5
    assert result.extra_payload["duration_seconds"] == 180.0
    assert result.extra_payload["color"] == "#ffffff"


def test_uses_configured_color():
    theme = ProgressBarTheme()
    now_playing = _now_playing(position=1.0, duration=10.0)
    result = theme.prepare(
        now_playing, _artwork(), None, None, None, ProgressBarConfig(color="#ff8800")
    )
    assert result.extra_payload["color"] == "#ff8800"


def test_returns_none_when_position_unknown():
    theme = ProgressBarTheme()
    now_playing = _now_playing(position=None, duration=180.0)
    assert theme.prepare(now_playing, _artwork(), None, None, None, ProgressBarConfig()) is None


def test_returns_none_when_duration_unknown():
    theme = ProgressBarTheme()
    now_playing = _now_playing(position=10.0, duration=None)
    assert theme.prepare(now_playing, _artwork(), None, None, None, ProgressBarConfig()) is None


def test_returns_none_when_duration_zero():
    theme = ProgressBarTheme()
    now_playing = _now_playing(position=0.0, duration=0.0)
    assert theme.prepare(now_playing, _artwork(), None, None, None, ProgressBarConfig()) is None


def test_position_zero_is_valid_not_falsy():
    theme = ProgressBarTheme()
    now_playing = _now_playing(position=0.0, duration=180.0)
    result = theme.prepare(now_playing, _artwork(), None, None, None, ProgressBarConfig())
    assert result.extra_payload["position_seconds"] == 0.0


# ---------------------------------------------------------------------------
# client_assets()
# ---------------------------------------------------------------------------


def test_client_assets_registers_theme_handler():
    theme = ProgressBarTheme()
    assets = theme.client_assets(ProgressBarConfig())
    assert "window.themeHandlers.progress_bar" in assets.js
    assert "theme-progress-bar" in assets.css


@pytest.mark.parametrize("position", ["top", "bottom"])
def test_client_assets_includes_configured_position(position):
    theme = ProgressBarTheme()
    assets = theme.client_assets(ProgressBarConfig(position=position))
    assert f"position-{position}" in assets.js


def test_client_assets_falls_back_to_bottom_for_invalid_position():
    theme = ProgressBarTheme()
    assets = theme.client_assets(ProgressBarConfig(position="nonsense; </script>"))
    assert "position-bottom" in assets.js
    assert "nonsense" not in assets.js


def test_client_assets_uses_configured_thickness():
    theme = ProgressBarTheme()
    assets = theme.client_assets(ProgressBarConfig(thickness_px=12))
    assert "height: 12px;" in assets.css


def test_client_assets_clamps_thickness_to_at_least_one():
    theme = ProgressBarTheme()
    assets = theme.client_assets(ProgressBarConfig(thickness_px=0))
    assert "height: 1px;" in assets.css
