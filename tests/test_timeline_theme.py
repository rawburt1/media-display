"""Tests for the Timeline theme (mediainfo/themes/timeline.py)."""

from mediainfo.config.themes import TimelineConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.timeline import TimelineTheme, _extract_albums


def _music(discography=None, album="Houses of the Holy"):
    return NowPlaying(
        source="kodi", media_type="music", title="No Quarter", subtitle="Led Zeppelin",
        album=album, discography=discography or [],
    )


def _artwork():
    return Artwork(url="https://example.com/art.jpg", label="Album art")


# ---------------------------------------------------------------------------
# _extract_albums
# ---------------------------------------------------------------------------

def test_extract_albums_dedupes_preserving_order():
    discography = [
        "Houses of the Holy – No Quarter",
        "Houses of the Holy – The Rain Song",
        "Physical Graffiti – Kashmir",
        "IV – Stairway to Heaven",
    ]
    assert _extract_albums(discography, max_albums=10) == [
        "Houses of the Holy", "Physical Graffiti", "IV",
    ]


def test_extract_albums_skips_entries_without_album():
    discography = ["Some Track With No Album", "IV – Stairway to Heaven"]
    assert _extract_albums(discography, max_albums=10) == ["IV"]


def test_extract_albums_respects_max_albums():
    discography = [f"Album{i} – Track{i}" for i in range(5)]
    assert len(_extract_albums(discography, max_albums=2)) == 2


def test_extract_albums_empty_input():
    assert _extract_albums([], max_albums=10) == []


# ---------------------------------------------------------------------------
# prepare()
# ---------------------------------------------------------------------------

def test_music_with_discography_includes_current_album():
    theme = TimelineTheme()
    discography = ["IV – Stairway to Heaven", "Physical Graffiti – Kashmir"]
    now_playing = _music(discography=discography, album="Houses of the Holy")

    result = theme.prepare(now_playing, _artwork(), None, None, None, TimelineConfig())

    assert result.extra_payload["current"] == "Houses of the Holy"
    assert "Houses of the Holy" in result.extra_payload["albums"]
    assert "IV" in result.extra_payload["albums"]
    assert theme.health_detail(TimelineConfig()) is None


def test_music_with_discography_does_not_duplicate_current_album():
    theme = TimelineTheme()
    discography = ["Houses of the Holy – No Quarter", "IV – Stairway to Heaven"]
    now_playing = _music(discography=discography, album="Houses of the Holy")

    result = theme.prepare(now_playing, _artwork(), None, None, None, TimelineConfig())

    assert result.extra_payload["albums"].count("Houses of the Holy") == 1


def test_music_without_discography_degrades_to_current_album():
    theme = TimelineTheme()
    now_playing = _music(discography=[], album="Houses of the Holy")

    result = theme.prepare(now_playing, _artwork(), None, None, None, TimelineConfig())

    assert result.extra_payload["albums"] == ["Houses of the Holy"]
    detail = theme.health_detail(TimelineConfig())
    assert detail["degraded"] is True
    assert "Lidarr" in detail["reason"]


def test_music_without_discography_or_album_returns_none():
    theme = TimelineTheme()
    now_playing = _music(discography=[], album="")

    result = theme.prepare(now_playing, _artwork(), None, None, None, TimelineConfig())

    assert result is None
    detail = theme.health_detail(TimelineConfig())
    assert detail["degraded"] is True


def test_movie_returns_none_and_clears_degraded_state():
    theme = TimelineTheme()
    # First a degraded music tick...
    theme.prepare(_music(discography=[], album="X"), _artwork(), None, None, None, TimelineConfig())
    assert theme.health_detail(TimelineConfig()) is not None

    # ...then a movie tick should reset health back to clean (not "still
    # degraded from the last music track").
    movie = NowPlaying(source="kodi", media_type="movie", title="Alien")
    result = theme.prepare(movie, _artwork(), None, None, None, TimelineConfig())

    assert result is None
    assert theme.health_detail(TimelineConfig()) is None


def test_max_albums_cap_still_leaves_room_for_current_album():
    theme = TimelineTheme()
    discography = [f"Album{i} – Track{i}" for i in range(5)]
    now_playing = _music(discography=discography, album="Current Album")

    result = theme.prepare(now_playing, _artwork(), None, None, None, TimelineConfig(max_albums=3))

    albums = result.extra_payload["albums"]
    assert len(albums) <= 3
    assert "Current Album" in albums


# ---------------------------------------------------------------------------
# health_detail() default state
# ---------------------------------------------------------------------------

def test_health_detail_none_before_any_prepare_call():
    theme = TimelineTheme()
    assert theme.health_detail(TimelineConfig()) is None


# ---------------------------------------------------------------------------
# client_assets()
# ---------------------------------------------------------------------------

def test_client_assets_registers_theme_handler():
    theme = TimelineTheme()
    assets = theme.client_assets(TimelineConfig())
    assert "window.themeHandlers.timeline" in assets.js
    assert "theme-timeline" in assets.css


def test_client_assets_falls_back_to_top_left_for_invalid_corner():
    theme = TimelineTheme()
    assets = theme.client_assets(TimelineConfig(corner="nonsense; </script>"))
    assert "corner-top-left" in assets.js
    assert "nonsense" not in assets.js
