"""Tests for the Mopidy source."""

from unittest.mock import MagicMock, patch

from mediainfo.config import MopidyConfig
from mediainfo.sources.mopidy import MopidySource


def _source(**kwargs) -> MopidySource:
    defaults = dict(enabled=True, host="192.168.1.30", port=6680)
    defaults.update(kwargs)
    return MopidySource(MopidyConfig(**defaults))


def _responses(state, track=None, position_ms=None, images=None):
    state_response = MagicMock()
    state_response.json.return_value = {"result": state}
    responses = [state_response]

    if state == "playing":
        track_response = MagicMock()
        track_response.json.return_value = {"result": track}
        responses.append(track_response)

        if track:
            position_response = MagicMock()
            position_response.json.return_value = {"result": position_ms}
            responses.append(position_response)

            images_response = MagicMock()
            images_response.json.return_value = {"result": images or {}}
            responses.append(images_response)

    return responses


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_stopped_returns_none(mock_post):
    mock_post.side_effect = _responses("stopped")

    source = _source()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is False


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_paused_returns_none(mock_post):
    mock_post.side_effect = _responses("paused")

    source = _source()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is False


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_playing_track(mock_post):
    track = {
        "uri": "spotify:track:abc123",
        "name": "Bohemian Rhapsody",
        "artists": [{"name": "Queen"}],
        "album": {"name": "A Night at the Opera"},
        "length": 355000,
    }
    mock_post.side_effect = _responses(
        "playing",
        track,
        position_ms=12000,
        images={"spotify:track:abc123": [{"uri": "https://i.scdn.co/image/abc.jpg"}]},
    )

    result = _source().get_now_playing()

    assert result is not None
    assert result.source == "mopidy"
    assert result.media_type == "music"
    assert result.title == "Bohemian Rhapsody"
    assert result.subtitle == "Queen"
    assert result.artist == "Queen"
    assert result.album == "A Night at the Opera"
    assert result.position_seconds == 12.0
    assert result.duration_seconds == 355.0
    assert len(result.images) == 1
    assert result.images[0].url == "https://i.scdn.co/image/abc.jpg"


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_relative_image_uri_is_resolved_against_mopidy_host(mock_post):
    track = {"uri": "local:track:x", "name": "T", "artists": [{"name": "A"}], "album": {}}
    mock_post.side_effect = _responses(
        "playing",
        track,
        position_ms=0,
        images={"local:track:x": [{"uri": "/local/images/abc.jpg"}]},
    )

    result = _source(host="192.168.1.30", port=6680).get_now_playing()

    assert result.images[0].url == "http://192.168.1.30:6680/local/images/abc.jpg"


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_no_current_track_returns_none(mock_post):
    mock_post.side_effect = _responses("playing", track=None)

    result = _source().get_now_playing()

    assert result is None


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_missing_artist_and_album_default_to_empty(mock_post):
    track = {"uri": "local:track:y", "name": "Untitled", "artists": [], "album": None}
    mock_post.side_effect = _responses("playing", track, position_ms=0, images={})

    result = _source().get_now_playing()

    assert result.subtitle == ""
    assert result.album == ""
    assert result.images == []


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_image_lookup_failure_is_not_fatal(mock_post):
    track = {"uri": "local:track:z", "name": "T", "artists": [{"name": "A"}], "album": {}}
    state_response = MagicMock()
    state_response.json.return_value = {"result": "playing"}
    track_response = MagicMock()
    track_response.json.return_value = {"result": track}
    position_response = MagicMock()
    position_response.json.return_value = {"result": 0}
    mock_post.side_effect = [state_response, track_response, position_response, Exception("boom")]

    source = _source()
    result = source.get_now_playing()

    assert result is not None
    assert result.images == []
    assert source.last_poll_failed is False


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_connection_error_sets_last_poll_failed(mock_post):
    mock_post.side_effect = Exception("connection refused")

    source = _source()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is True


def test_config_disabled_by_default():
    assert MopidyConfig().enabled is False


def test_config_defaults():
    cfg = MopidyConfig()
    assert cfg.host == "localhost"
    assert cfg.port == 6680
    assert cfg.timeout == 5.0
