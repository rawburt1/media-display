"""Tests for the foobar2000 (Beefweb) source."""

from typing import Any
from unittest.mock import MagicMock, patch

from mediainfo.config import Foobar2000Config
from mediainfo.sources.foobar2000 import Foobar2000Source


def _source(**kwargs) -> Foobar2000Source:
    defaults: dict[str, Any] = dict(enabled=True, host="192.168.1.70", port=8888)
    defaults.update(kwargs)
    return Foobar2000Source(Foobar2000Config(**defaults))


def _response(player=None):
    response = MagicMock()
    response.json.return_value = {"player": player or {}}
    return response


@patch("mediainfo.sources.foobar2000.requests.get")
def test_stopped_returns_none(mock_get):
    mock_get.return_value = _response({"playbackState": "stopped"})

    source = _source()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is False


@patch("mediainfo.sources.foobar2000.requests.get")
def test_paused_returns_none(mock_get):
    mock_get.return_value = _response({"playbackState": "paused"})

    assert _source().get_now_playing() is None


@patch("mediainfo.sources.foobar2000.requests.get")
def test_playing_track(mock_get):
    mock_get.return_value = _response(
        {
            "playbackState": "playing",
            "activeItem": {
                "playlistId": "pl1",
                "index": 3,
                "position": 42.5,
                "duration": 213.0,
                "columns": ["Queen", "A Night at the Opera", "Bohemian Rhapsody"],
            },
        }
    )

    result = _source().get_now_playing()

    assert result is not None
    assert result.source == "foobar2000"
    assert result.media_type == "music"
    assert result.title == "Bohemian Rhapsody"
    assert result.subtitle == "Queen"
    assert result.artist == "Queen"
    assert result.album == "A Night at the Opera"
    assert result.position_seconds == 42.5
    assert result.duration_seconds == 213.0
    assert result.images[0].url == "http://192.168.1.70:8888/api/artwork/pl1/3"

    params = mock_get.call_args.kwargs["params"]
    assert params == {"columns": "%artist%,%album%,%title%"}


@patch("mediainfo.sources.foobar2000.requests.get")
def test_no_title_returns_none(mock_get):
    mock_get.return_value = _response(
        {"playbackState": "playing", "activeItem": {"columns": ["", "", ""]}}
    )

    assert _source().get_now_playing() is None


@patch("mediainfo.sources.foobar2000.requests.get")
def test_missing_artist_and_album_default_to_empty(mock_get):
    mock_get.return_value = _response(
        {"playbackState": "playing", "activeItem": {"columns": ["", "", "Untitled Track"]}}
    )

    result = _source().get_now_playing()

    assert result.title == "Untitled Track"
    assert result.subtitle == ""
    assert result.album == ""


@patch("mediainfo.sources.foobar2000.requests.get")
def test_no_active_item_returns_none(mock_get):
    mock_get.return_value = _response({"playbackState": "playing"})

    assert _source().get_now_playing() is None


@patch("mediainfo.sources.foobar2000.requests.get")
def test_missing_playlist_info_means_no_artwork(mock_get):
    mock_get.return_value = _response(
        {"playbackState": "playing", "activeItem": {"columns": ["A", "B", "T"]}}
    )

    result = _source().get_now_playing()

    assert result.images == []


def test_unsupported_api_type_fails_clearly():
    source = _source(api_type="mp2yfc")
    assert source.get_now_playing() is None
    assert source.last_poll_failed is True


@patch("mediainfo.sources.foobar2000.requests.get")
def test_connection_error_sets_last_poll_failed(mock_get):
    mock_get.side_effect = Exception("connection refused")

    source = _source()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is True


def test_config_disabled_by_default():
    assert Foobar2000Config().enabled is False


def test_config_defaults():
    cfg = Foobar2000Config()
    assert cfg.host == "localhost"
    assert cfg.port == 8888
    assert cfg.api_type == "beefweb"
    assert cfg.timeout == 5.0
