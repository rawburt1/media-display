"""Tests for the vinyl (turntable recognition) source."""

from unittest.mock import MagicMock, patch

from pixoo_media.config import VinylConfig
from pixoo_media.sources.vinyl import VinylSource


def _source(**kwargs) -> VinylSource:
    defaults = dict(enabled=True, host="192.168.1.40", port=8091)
    defaults.update(kwargs)
    return VinylSource(VinylConfig(**defaults))


@patch("pixoo_media.sources.vinyl.requests.get")
def test_returns_now_playing_with_artwork(mock_get):
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

    assert now_playing.source == "vinyl"
    assert now_playing.media_type == "music"
    assert now_playing.title == "Comfortably Numb"
    assert now_playing.subtitle == "Pink Floyd"
    assert now_playing.album == "The Wall"
    assert now_playing.images[0].url == "https://example.com/cover.jpg"
    assert now_playing.images[0].label == "Album art (AudD)"

    args, _ = mock_get.call_args
    assert args[0] == "http://192.168.1.40:8091/now-playing"


@patch("pixoo_media.sources.vinyl.requests.get")
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


@patch("pixoo_media.sources.vinyl.requests.get")
def test_returns_none_when_nothing_recognized(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {}
    mock_get.return_value = mock_response

    assert _source().get_now_playing() is None


@patch("pixoo_media.sources.vinyl.requests.get")
def test_returns_none_on_connection_error(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")

    assert _source().get_now_playing() is None
