"""Tests for the Home Assistant media_player source (WebSocket API).

The real WebSocketApp/background thread (started in __init__) is never
actually run here - threading.Thread.start is patched out for every test,
and messages are fed directly into _on_message() to simulate what the
connection would otherwise deliver.
"""

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mediainfo.config import HomeAssistantConfig
from mediainfo.sources.homeassistant import HomeAssistantSource


@pytest.fixture(autouse=True)
def no_real_connection():
    with patch("threading.Thread.start", lambda self: None):
        yield


def _source(**kwargs) -> HomeAssistantSource:
    defaults: dict[str, Any] = dict(
        enabled=True,
        host="192.168.1.11",
        port=8123,
        token="test-token",
        entity_id="media_player.apple_tv_4k",
    )
    defaults.update(kwargs)
    return HomeAssistantSource(HomeAssistantConfig(**defaults))


def _authenticate(source, ws=None):
    ws = ws or MagicMock()
    source._on_message(ws, json.dumps({"type": "auth_required"}))
    source._on_message(ws, json.dumps({"type": "auth_ok"}))
    return ws


def _state_changed(entity_id, state, attributes=None):
    return json.dumps(
        {
            "type": "event",
            "event": {
                "event_type": "state_changed",
                "data": {
                    "entity_id": entity_id,
                    "new_state": {"state": state, "attributes": attributes or {}},
                },
            },
        }
    )


def _get_states_result(entities):
    return json.dumps({"type": "result", "result": entities})


# ---------------------------------------------------------------------------
# Connection URL
# ---------------------------------------------------------------------------


def test_ws_url_uses_ws_by_default():
    source = _source()
    assert source._ws_url == "ws://192.168.1.11:8123/api/websocket"


def test_ws_url_uses_wss_when_use_ssl():
    source = _source(use_ssl=True)
    assert source._ws_url == "wss://192.168.1.11:8123/api/websocket"


# ---------------------------------------------------------------------------
# Auth handshake
# ---------------------------------------------------------------------------


def test_sends_auth_message_on_auth_required():
    source = _source()
    ws = MagicMock()

    source._on_message(ws, json.dumps({"type": "auth_required"}))

    ws.send.assert_called_once_with(json.dumps({"type": "auth", "access_token": "test-token"}))


def test_subscribes_and_fetches_states_on_auth_ok():
    source = _source()
    ws = MagicMock()

    source._on_message(ws, json.dumps({"type": "auth_ok"}))

    sent_types = [json.loads(c.args[0])["type"] for c in ws.send.call_args_list]
    assert "subscribe_events" in sent_types
    assert "get_states" in sent_types


def test_auth_ok_marks_connected():
    source = _source()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is True  # never connected yet

    _authenticate(source)

    source.get_now_playing()
    assert source.last_poll_failed is False


def test_auth_invalid_marks_auth_failed():
    source = _source()

    source._on_message(MagicMock(), json.dumps({"type": "auth_invalid"}))

    assert source.get_now_playing() is None
    assert source.last_poll_failed is True


def test_not_yet_connected_sets_last_poll_failed():
    source = _source()

    assert source.get_now_playing() is None
    assert source.last_poll_failed is True


def test_on_close_marks_disconnected():
    source = _source()
    _authenticate(source)

    source._on_close(MagicMock(), 1000, "bye")

    assert source.get_now_playing() is None
    assert source.last_poll_failed is True


def test_malformed_message_is_ignored_not_fatal():
    source = _source()
    source._on_message(MagicMock(), "not json{{{")  # must not raise


# ---------------------------------------------------------------------------
# get_states snapshot + state_changed events -> entity cache
# ---------------------------------------------------------------------------


def test_get_states_result_populates_entity_cache():
    source = _source()
    _authenticate(source)

    source._on_message(
        MagicMock(),
        _get_states_result(
            [
                {
                    "entity_id": "media_player.apple_tv_4k",
                    "state": "playing",
                    "attributes": {"media_title": "X"},
                },
                {"entity_id": "sensor.temperature", "state": "21", "attributes": {}},
            ]
        ),
    )

    assert "media_player.apple_tv_4k" in source._entities
    assert "sensor.temperature" not in source._entities  # non-media_player domain ignored


def test_state_changed_event_updates_entity_cache():
    source = _source()
    _authenticate(source)

    source._on_message(
        MagicMock(), _state_changed("media_player.apple_tv_4k", "playing", {"media_title": "X"})
    )

    assert source._entities["media_player.apple_tv_4k"]["state"] == "playing"


# ---------------------------------------------------------------------------
# get_now_playing() with a configured entity_id
# ---------------------------------------------------------------------------


def test_idle_state_returns_none():
    source = _source()
    _authenticate(source)
    source._on_message(MagicMock(), _state_changed("media_player.apple_tv_4k", "idle"))

    assert source.get_now_playing() is None


def test_paused_state_returns_none():
    source = _source()
    _authenticate(source)
    source._on_message(
        MagicMock(), _state_changed("media_player.apple_tv_4k", "paused", {"media_title": "X"})
    )

    assert source.get_now_playing() is None


def test_playing_video_without_series_info_is_movie():
    source = _source()
    _authenticate(source)
    source._on_message(
        MagicMock(),
        _state_changed(
            "media_player.apple_tv_4k",
            "playing",
            {
                "media_content_type": "video",
                "media_title": "Brottsplats: Wales",
                "app_name": "SVT Play",
                "entity_picture": "/api/media_player_proxy/media_player.apple_tv_4k?token=abc",
            },
        ),
    )

    now_playing = source.get_now_playing()

    assert now_playing.media_type == "movie"
    assert now_playing.title == "Brottsplats: Wales"
    assert now_playing.subtitle == "SVT Play"
    assert now_playing.images[0].url == (
        "http://192.168.1.11:8123/api/media_player_proxy/media_player.apple_tv_4k?token=abc"
    )
    assert now_playing.images[0].label == "Artwork (Home Assistant)"


def test_playing_episode_with_series_info():
    source = _source()
    _authenticate(source)
    source._on_message(
        MagicMock(),
        _state_changed(
            "media_player.apple_tv_4k",
            "playing",
            {
                "media_content_type": "tvshow",
                "media_series_title": "Breaking Bad",
                "media_title": "Pilot",
                "media_season": 1,
                "media_episode": 1,
            },
        ),
    )

    now_playing = source.get_now_playing()

    assert now_playing.media_type == "episode"
    assert now_playing.title == "Breaking Bad"
    assert now_playing.subtitle == "S01E01 - Pilot"
    assert now_playing.season == 1


def test_playing_music():
    source = _source()
    _authenticate(source)
    source._on_message(
        MagicMock(),
        _state_changed(
            "media_player.apple_tv_4k",
            "playing",
            {
                "media_content_type": "music",
                "media_title": "Comfortably Numb",
                "media_artist": "Pink Floyd",
                "media_album_name": "The Wall",
            },
        ),
    )

    now_playing = source.get_now_playing()

    assert now_playing.media_type == "music"
    assert now_playing.title == "Comfortably Numb"
    assert now_playing.subtitle == "Pink Floyd"
    assert now_playing.album == "The Wall"


def test_uses_https_for_artwork_when_use_ssl():
    source = _source(use_ssl=True)
    _authenticate(source)
    source._on_message(
        MagicMock(),
        _state_changed(
            "media_player.apple_tv_4k",
            "playing",
            {
                "entity_picture": "/img.jpg",
                "media_title": "X",
            },
        ),
    )

    now_playing = source.get_now_playing()
    assert now_playing.images[0].url.startswith("https://")


def test_configured_entity_id_ignores_other_entities():
    source = _source(entity_id="media_player.apple_tv_4k")
    _authenticate(source)
    source._on_message(
        MagicMock(),
        _state_changed("media_player.other_device", "playing", {"media_title": "Other"}),
    )

    assert source.get_now_playing() is None


# ---------------------------------------------------------------------------
# Auto-select (blank entity_id) - mirrors the LMS source's pattern
# ---------------------------------------------------------------------------


def test_auto_select_prefers_playing_over_paused():
    source = _source(entity_id="")
    _authenticate(source)
    source._on_message(
        MagicMock(), _state_changed("media_player.a", "paused", {"media_title": "A"})
    )
    source._on_message(
        MagicMock(), _state_changed("media_player.b", "playing", {"media_title": "B"})
    )

    now_playing = source.get_now_playing()
    assert now_playing.title == "B"


def test_auto_select_picks_most_recently_updated_playing(monkeypatch):
    source = _source(entity_id="")
    _authenticate(source)

    real_monotonic = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real_monotonic())
    source._on_message(
        MagicMock(), _state_changed("media_player.a", "playing", {"media_title": "A"})
    )

    monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + 5)
    source._on_message(
        MagicMock(), _state_changed("media_player.b", "playing", {"media_title": "B"})
    )

    now_playing = source.get_now_playing()
    assert now_playing.title == "B"


def test_auto_select_no_entities_returns_none():
    source = _source(entity_id="")
    _authenticate(source)

    assert source.get_now_playing() is None


def test_auto_select_only_paused_still_reports_idle():
    source = _source(entity_id="")
    _authenticate(source)
    source._on_message(
        MagicMock(), _state_changed("media_player.a", "paused", {"media_title": "A"})
    )

    assert source.get_now_playing() is None


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


def test_health_check_reports_disconnected_by_default():
    source = _source()
    assert source.health_check() == {"connected": False}


def test_health_check_reports_connected_after_authentication():
    source = _source()
    _authenticate(source)
    assert source.health_check() == {"connected": True}


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


def test_config_entity_id_defaults_to_blank():
    assert HomeAssistantConfig().entity_id == ""
