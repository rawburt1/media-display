"""Tests for the VLC source."""

from typing import Any
from unittest.mock import MagicMock, patch

from mediainfo.config import VlcConfig
from mediainfo.sources.vlc import VlcSource


def _source(**kwargs) -> VlcSource:
    defaults: dict[str, Any] = dict(enabled=True, host="192.168.1.60", port=8080, password="secret")
    defaults.update(kwargs)
    return VlcSource(VlcConfig(**defaults))


def _response(status_code=200, json_data=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return response


@patch("mediainfo.sources.vlc.requests.get")
def test_stopped_returns_none(mock_get):
    mock_get.return_value = _response(json_data={"state": "stopped"})

    source = _source()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is False


@patch("mediainfo.sources.vlc.requests.get")
def test_paused_returns_none(mock_get):
    mock_get.return_value = _response(json_data={"state": "paused"})

    assert _source().get_now_playing() is None


@patch("mediainfo.sources.vlc.requests.get")
def test_playing_track(mock_get):
    mock_get.return_value = _response(
        json_data={
            "state": "playing",
            "time": 42,
            "length": 213,
            "information": {
                "category": {
                    "meta": {"title": "Bohemian Rhapsody", "artist": "Queen", "album": "A Night at the Opera"}
                }
            },
        }
    )

    result = _source().get_now_playing()

    assert result is not None
    assert result.source == "vlc"
    assert result.title == "Bohemian Rhapsody"
    assert result.subtitle == "Queen"
    assert result.artist == "Queen"
    assert result.album == "A Night at the Opera"
    assert result.media_type == "music"
    assert result.position_seconds == 42.0
    assert result.duration_seconds == 213.0
    assert result.images[0].url == "http://192.168.1.60:8080/art"
    assert result.images[0].auth == ("", "secret")


@patch("mediainfo.sources.vlc.requests.get")
def test_no_metadata_falls_back_to_filename(mock_get):
    mock_get.return_value = _response(
        json_data={
            "state": "playing",
            "information": {"category": {"meta": {"filename": "movie.mkv"}}},
        }
    )

    result = _source().get_now_playing()

    assert result.title == "movie.mkv"
    assert result.media_type == "movie"


@patch("mediainfo.sources.vlc.requests.get")
def test_now_playing_field_is_split_into_artist_and_title(mock_get):
    mock_get.return_value = _response(
        json_data={
            "state": "playing",
            "information": {"category": {"meta": {"now_playing": "Daft Punk - One More Time"}}},
        }
    )

    result = _source().get_now_playing()

    assert result.artist == "Daft Punk"
    assert result.title == "One More Time"


@patch("mediainfo.sources.vlc.requests.get")
def test_now_playing_field_without_dash_is_used_as_title(mock_get):
    mock_get.return_value = _response(
        json_data={
            "state": "playing",
            "information": {"category": {"meta": {"now_playing": "Live Radio Show"}}},
        }
    )

    result = _source().get_now_playing()

    assert result.title == "Live Radio Show"
    assert result.artist == ""


@patch("mediainfo.sources.vlc.requests.get")
def test_no_title_at_all_returns_none(mock_get):
    mock_get.return_value = _response(json_data={"state": "playing", "information": {"category": {"meta": {}}}})

    assert _source().get_now_playing() is None


@patch("mediainfo.sources.vlc.requests.get")
def test_auth_failure_sets_last_poll_failed(mock_get):
    mock_get.return_value = _response(status_code=401)

    source = _source()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is True


@patch("mediainfo.sources.vlc.requests.get")
def test_connection_error_sets_last_poll_failed(mock_get):
    mock_get.side_effect = Exception("connection refused")

    source = _source()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is True


@patch("mediainfo.sources.vlc.requests.get")
def test_no_password_sends_no_auth(mock_get):
    mock_get.return_value = _response(json_data={"state": "stopped"})

    _source(password="").get_now_playing()

    assert mock_get.call_args.kwargs["auth"] is None


def test_config_disabled_by_default():
    assert VlcConfig().enabled is False


def test_config_defaults():
    cfg = VlcConfig()
    assert cfg.host == "localhost"
    assert cfg.port == 8080
    assert cfg.password == ""
    assert cfg.timeout == 5.0
