"""Tests for the vinyl (turntable recognition) source."""

from unittest.mock import MagicMock, patch

from mediainfo.config import VinylConfig
from mediainfo.sources.vinyl import VinylSource


def _source(**kwargs) -> VinylSource:
    defaults = dict(enabled=True, host="192.168.1.40", port=8091)
    defaults.update(kwargs)
    return VinylSource(VinylConfig(**defaults))


@patch("mediainfo.sources.vinyl.requests.get")
def test_returns_now_playing_with_artwork(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "https://example.com/cover.jpg",
        "provider": "audd",
    }
    mock_get.return_value = mock_response

    now_playing = _source().get_now_playing()

    assert now_playing.source == "vinyl"
    assert now_playing.media_type == "music"
    assert now_playing.title == "Comfortably Numb"
    assert now_playing.subtitle == "Pink Floyd"
    assert now_playing.album == "The Wall"
    assert now_playing.images[0].url == "https://example.com/cover.jpg"
    assert now_playing.images[0].label == "Album art (AudD)"

    args, _ = mock_get.call_args
    assert args[0] == "http://192.168.1.40:8091/now-playing"


@patch("mediainfo.sources.vinyl.requests.get")
def test_artwork_label_reflects_shazam_provider(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "https://example.com/cover.jpg",
        "provider": "shazam",
    }
    mock_get.return_value = mock_response

    now_playing = _source().get_now_playing()

    assert now_playing.images[0].label == "Album art (Shazam)"


@patch("mediainfo.sources.vinyl.requests.get")
def test_artwork_label_reflects_local_folder_fallback_provider(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "https://example.com/cover.jpg",
        "provider": "local_folder",
    }
    mock_get.return_value = mock_response

    now_playing = _source().get_now_playing()

    assert now_playing.images[0].label == "Album art (local folder)"


@patch("mediainfo.sources.vinyl.requests.get")
def test_artwork_label_falls_back_to_generic_when_provider_missing(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "https://example.com/cover.jpg",
    }
    mock_get.return_value = mock_response

    now_playing = _source().get_now_playing()

    assert now_playing.images[0].label == "Album art (vinyl_recognizer)"


@patch("mediainfo.sources.vinyl.requests.get")
def test_returns_now_playing_without_artwork(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "",
    }
    mock_get.return_value = mock_response

    now_playing = _source().get_now_playing()

    assert now_playing.images == []


@patch("mediainfo.sources.vinyl.requests.get")
def test_returns_none_when_nothing_recognized(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {}
    mock_get.return_value = mock_response

    assert _source().get_now_playing() is None


@patch("mediainfo.sources.vinyl.requests.get")
def test_returns_none_on_connection_error(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")

    source = _source()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is True
