"""Tests for the Home Assistant media_player source."""

from unittest.mock import MagicMock, patch

from mediainfo.config import HomeAssistantConfig
from mediainfo.sources.homeassistant import HomeAssistantSource


def _source(**kwargs) -> HomeAssistantSource:
    defaults = dict(
        enabled=True,
        host="192.168.1.11",
        port=8123,
        token="test-token",
        entity_id="media_player.apple_tv_4k",
    )
    defaults.update(kwargs)
    return HomeAssistantSource(HomeAssistantConfig(**defaults))


def _response(state, attributes=None):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"state": state, "attributes": attributes or {}}
    return response


@patch("mediainfo.sources.homeassistant.requests.get")
def test_sends_bearer_token_and_entity_path(mock_get):
    mock_get.return_value = _response("idle")

    _source().get_now_playing()

    args, kwargs = mock_get.call_args
    assert args[0] == "http://192.168.1.11:8123/api/states/media_player.apple_tv_4k"
    assert kwargs["headers"] == {"Authorization": "Bearer test-token"}


@patch("mediainfo.sources.homeassistant.requests.get")
def test_uses_https_when_configured(mock_get):
    mock_get.return_value = _response("idle")

    _source(use_ssl=True).get_now_playing()

    args, _ = mock_get.call_args
    assert args[0].startswith("https://")


@patch("mediainfo.sources.homeassistant.requests.get")
def test_idle_state_returns_none(mock_get):
    mock_get.return_value = _response("idle")

    assert _source().get_now_playing() is None


@patch("mediainfo.sources.homeassistant.requests.get")
def test_paused_state_returns_none(mock_get):
    mock_get.return_value = _response("paused", {"media_title": "Brottsplats: Wales"})

    assert _source().get_now_playing() is None


@patch("mediainfo.sources.homeassistant.requests.get")
def test_playing_video_without_series_info_is_movie(mock_get):
    mock_get.return_value = _response("playing", {
        "media_content_type": "video",
        "media_title": "Brottsplats: Wales",
        "app_name": "SVT Play",
        "entity_picture": "/api/media_player_proxy/media_player.apple_tv_4k?token=abc",
    })

    now_playing = _source().get_now_playing()

    assert now_playing.media_type == "movie"
    assert now_playing.title == "Brottsplats: Wales"
    assert now_playing.subtitle == "SVT Play"
    assert now_playing.images[0].url == (
        "http://192.168.1.11:8123/api/media_player_proxy/media_player.apple_tv_4k?token=abc"
    )
    assert now_playing.images[0].label == "Artwork (Home Assistant)"


@patch("mediainfo.sources.homeassistant.requests.get")
def test_playing_episode_with_series_info(mock_get):
    mock_get.return_value = _response("playing", {
        "media_content_type": "tvshow",
        "media_series_title": "Breaking Bad",
        "media_title": "Pilot",
        "media_season": 1,
        "media_episode": 1,
    })

    now_playing = _source().get_now_playing()

    assert now_playing.media_type == "episode"
    assert now_playing.title == "Breaking Bad"
    assert now_playing.subtitle == "S01E01 - Pilot"
    assert now_playing.season == 1


@patch("mediainfo.sources.homeassistant.requests.get")
def test_playing_music(mock_get):
    mock_get.return_value = _response("playing", {
        "media_content_type": "music",
        "media_title": "Comfortably Numb",
        "media_artist": "Pink Floyd",
        "media_album_name": "The Wall",
    })

    now_playing = _source().get_now_playing()

    assert now_playing.media_type == "music"
    assert now_playing.title == "Comfortably Numb"
    assert now_playing.subtitle == "Pink Floyd"
    assert now_playing.album == "The Wall"


@patch("mediainfo.sources.homeassistant.requests.get")
def test_api_error_sets_last_poll_failed(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")

    source = _source()
    result = source.get_now_playing()

    assert result is None
    assert source.last_poll_failed is True


@patch("mediainfo.sources.homeassistant.requests.get")
def test_successful_poll_clears_last_poll_failed(mock_get):
    mock_get.return_value = _response("idle")

    source = _source()
    source.last_poll_failed = True
    source.get_now_playing()

    assert source.last_poll_failed is False
