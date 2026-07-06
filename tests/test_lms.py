"""Tests for the Logitech Media Server (LMS) source."""

from unittest.mock import MagicMock, patch

from mediainfo.config import LmsConfig
from mediainfo.sources.lms import LmsSource


def _source(**kwargs) -> LmsSource:
    defaults = dict(enabled=True, host="192.168.1.50", port=9000)
    defaults.update(kwargs)
    return LmsSource(LmsConfig(**defaults))


def _response(result):
    response = MagicMock()
    response.json.return_value = {"result": result}
    return response


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_configured_player_id_playing(mock_post):
    mock_post.return_value = _response(
        {
            "mode": "play",
            "time": 12.5,
            "player_name": "Kitchen",
            "playlist_loop": [
                {"artist": "Queen", "album": "A Night at the Opera", "title": "Bohemian Rhapsody", "duration": 355}
            ],
        }
    )

    result = _source(player_id="aa:bb:cc:dd:ee:ff").get_now_playing()

    assert result is not None
    assert result.source == "lms"
    assert result.title == "Bohemian Rhapsody"
    assert result.subtitle == "Queen"
    assert result.artist == "Queen"
    assert result.album == "A Night at the Opera"
    assert result.device == "Kitchen"
    assert result.position_seconds == 12.5
    assert result.duration_seconds == 355.0

    payload = mock_post.call_args.kwargs["json"]
    assert payload["params"] == ["aa:bb:cc:dd:ee:ff", ["status", "-", 1, "tags:aldcK"]]


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_configured_player_stopped_returns_none(mock_post):
    mock_post.return_value = _response({"mode": "stop"})

    source = _source(player_id="aa:bb:cc:dd:ee:ff")
    assert source.get_now_playing() is None
    assert source.last_poll_failed is False


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_configured_player_paused_returns_none(mock_post):
    mock_post.return_value = _response({"mode": "pause"})

    assert _source(player_id="aa:bb:cc:dd:ee:ff").get_now_playing() is None


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_artwork_from_coverid(mock_post):
    mock_post.return_value = _response(
        {
            "mode": "play",
            "playlist_loop": [{"title": "T", "artist": "A", "album": "Al", "coverid": "abc123"}],
        }
    )

    result = _source(player_id="p1").get_now_playing()

    assert len(result.images) == 1
    assert result.images[0].url == "http://192.168.1.50:9000/music/abc123/cover.jpg"


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_artwork_from_absolute_artwork_url(mock_post):
    mock_post.return_value = _response(
        {
            "mode": "play",
            "playlist_loop": [
                {"title": "T", "artist": "A", "album": "Al", "artwork_url": "https://example.com/cover.jpg"}
            ],
        }
    )

    result = _source(player_id="p1").get_now_playing()

    assert result.images[0].url == "https://example.com/cover.jpg"


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_artwork_from_relative_artwork_url(mock_post):
    mock_post.return_value = _response(
        {
            "mode": "play",
            "playlist_loop": [{"title": "T", "artist": "A", "album": "Al", "artwork_url": "/imageproxy/x/cover.jpg"}],
        }
    )

    result = _source(player_id="p1").get_now_playing()

    assert result.images[0].url == "http://192.168.1.50:9000/imageproxy/x/cover.jpg"


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_no_artwork_available(mock_post):
    mock_post.return_value = _response({"mode": "play", "playlist_loop": [{"title": "T", "artist": "A"}]})

    result = _source(player_id="p1").get_now_playing()

    assert result.images == []


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_no_playlist_entry_returns_empty_title(mock_post):
    mock_post.return_value = _response({"mode": "play", "playlist_loop": []})

    result = _source(player_id="p1").get_now_playing()

    assert result is not None
    assert result.title == ""
    assert result.subtitle == ""


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_auto_select_prefers_playing_player(mock_post):
    players_response = _response(
        {"players_loop": [{"playerid": "p1", "name": "Living Room"}, {"playerid": "p2", "name": "Kitchen"}]}
    )
    p1_status = _response({"mode": "pause"})
    p2_status = _response({"mode": "play", "player_name": "Kitchen", "playlist_loop": [{"title": "Song"}]})
    mock_post.side_effect = [players_response, p1_status, p2_status]

    result = _source().get_now_playing()

    assert result is not None
    assert result.device == "Kitchen"


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_auto_select_falls_back_to_paused_player(mock_post):
    players_response = _response({"players_loop": [{"playerid": "p1", "name": "Living Room"}]})
    p1_status = _response({"mode": "pause"})
    mock_post.side_effect = [players_response, p1_status]

    # Selected player is paused -> still idle overall (paused == not shown,
    # consistent with every other source in this codebase).
    assert _source().get_now_playing() is None


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_auto_select_no_players_returns_none(mock_post):
    mock_post.return_value = _response({"players_loop": []})

    assert _source().get_now_playing() is None


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_player_status_query_failure_is_skipped_not_fatal(mock_post):
    players_response = _response({"players_loop": [{"playerid": "p1", "name": "A"}, {"playerid": "p2", "name": "B"}]})
    p2_status = _response({"mode": "play", "player_name": "B", "playlist_loop": [{"title": "Song"}]})
    mock_post.side_effect = [players_response, Exception("boom"), p2_status]

    source = _source()
    result = source.get_now_playing()

    assert result is not None
    assert result.device == "B"
    assert source.last_poll_failed is False


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_connection_error_sets_last_poll_failed(mock_post):
    mock_post.side_effect = Exception("connection refused")

    source = _source(player_id="p1")
    assert source.get_now_playing() is None
    assert source.last_poll_failed is True


def test_config_disabled_by_default():
    assert LmsConfig().enabled is False


def test_config_defaults():
    cfg = LmsConfig()
    assert cfg.host == "localhost"
    assert cfg.port == 9000
    assert cfg.player_id == ""
    assert cfg.timeout == 5.0
