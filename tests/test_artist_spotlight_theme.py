"""Tests for the Artist Spotlight theme (mediainfo/themes/artist_spotlight.py)."""

from pathlib import Path
from unittest.mock import MagicMock

from mediainfo.config.themes import ArtistSpotlightConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.artist_spotlight import ArtistSpotlightTheme, _resolve_artist


def _artwork():
    return Artwork(url="https://example.com/art.jpg", label="Album art")


def _music(artist="Manfred Mann's Earth Band"):
    return NowPlaying(source="kodi", media_type="music", title="Davy's on the Road Again", subtitle=artist)


def _svt_concert(artist="Some Band"):
    return NowPlaying(source="svt", media_type="episode", title="Konsert", artist=artist)


def _movie_no_artist():
    return NowPlaying(source="kodi", media_type="movie", title="Alien")


# ---------------------------------------------------------------------------
# _resolve_artist
# ---------------------------------------------------------------------------

def test_resolve_artist_music_uses_subtitle():
    assert _resolve_artist(_music(artist="Queen")) == "Queen"


def test_resolve_artist_svt_concert_uses_artist_field():
    assert _resolve_artist(_svt_concert(artist="ABBA")) == "ABBA"


def test_resolve_artist_movie_with_no_artist_field_is_empty():
    assert _resolve_artist(_movie_no_artist()) == ""


# ---------------------------------------------------------------------------
# prepare() / health_detail()
# ---------------------------------------------------------------------------

def test_music_with_photo_and_bio():
    theme = ArtistSpotlightTheme()
    media_data = MagicMock()
    media_data.get_artist_photo.return_value = Path("/cache/music/queen/artist.jpg")
    now_playing = _music(artist="Queen")
    now_playing.summary = "A British rock band formed in London."

    result = theme.prepare(now_playing, _artwork(), None, None, media_data, ArtistSpotlightConfig())

    assert result.extra_payload["name"] == "Queen"
    assert result.extra_payload["bio"] == "A British rock band formed in London."
    assert result.derived_image_path == Path("/cache/music/queen/artist.jpg")
    media_data.get_artist_photo.assert_called_once_with("Queen")
    assert theme.health_detail(ArtistSpotlightConfig()) is None


def test_show_bio_false_omits_bio_text():
    theme = ArtistSpotlightTheme()
    media_data = MagicMock()
    media_data.get_artist_photo.return_value = Path("/cache/music/queen/artist.jpg")
    now_playing = _music(artist="Queen")
    now_playing.summary = "A British rock band."

    result = theme.prepare(now_playing, _artwork(), None, None, media_data, ArtistSpotlightConfig(show_bio=False))

    assert result.extra_payload["bio"] == ""


def test_no_artist_name_returns_none_no_degraded_report():
    theme = ArtistSpotlightTheme()
    media_data = MagicMock()

    result = theme.prepare(_movie_no_artist(), _artwork(), None, None, media_data, ArtistSpotlightConfig())

    assert result is None
    media_data.get_artist_photo.assert_not_called()
    assert theme.health_detail(ArtistSpotlightConfig()) is None


def test_media_data_none_degrades():
    theme = ArtistSpotlightTheme()

    result = theme.prepare(_music(), _artwork(), None, None, None, ArtistSpotlightConfig())

    assert result is None
    detail = theme.health_detail(ArtistSpotlightConfig())
    assert detail["degraded"] is True
    assert "MediaDataStore" in detail["reason"]


def test_no_photo_found_degrades():
    theme = ArtistSpotlightTheme()
    media_data = MagicMock()
    media_data.get_artist_photo.return_value = None

    result = theme.prepare(_music(artist="Obscure Artist"), _artwork(), None, None, media_data, ArtistSpotlightConfig())

    assert result is None
    detail = theme.health_detail(ArtistSpotlightConfig())
    assert detail["degraded"] is True
    assert "Obscure Artist" in detail["reason"]


def test_svt_concert_broadcast_resolves_photo():
    theme = ArtistSpotlightTheme()
    media_data = MagicMock()
    media_data.get_artist_photo.return_value = Path("/cache/music/abba/artist.jpg")

    result = theme.prepare(_svt_concert(artist="ABBA"), _artwork(), None, None, media_data, ArtistSpotlightConfig())

    assert result.extra_payload["name"] == "ABBA"
    media_data.get_artist_photo.assert_called_once_with("ABBA")


def test_movie_after_degraded_music_clears_state():
    theme = ArtistSpotlightTheme()
    theme.prepare(_music(), _artwork(), None, None, None, ArtistSpotlightConfig())
    assert theme.health_detail(ArtistSpotlightConfig()) is not None

    result = theme.prepare(_movie_no_artist(), _artwork(), None, None, None, ArtistSpotlightConfig())

    assert result is None
    assert theme.health_detail(ArtistSpotlightConfig()) is None


# ---------------------------------------------------------------------------
# client_assets()
# ---------------------------------------------------------------------------

def test_client_assets_registers_theme_handler():
    theme = ArtistSpotlightTheme()
    assets = theme.client_assets(ArtistSpotlightConfig())
    assert "window.themeHandlers.artist_spotlight" in assets.js
    assert "theme-artist-spotlight" in assets.css


def test_client_assets_falls_back_to_bottom_left_for_invalid_corner():
    theme = ArtistSpotlightTheme()
    assets = theme.client_assets(ArtistSpotlightConfig(corner="nonsense; </script>"))
    assert "corner-bottom-left" in assets.js
    assert "nonsense" not in assets.js
