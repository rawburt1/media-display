"""Tests for the browser-extension WebSocket source.

The real Flask/flask_sock server (started in __init__) is never actually
run here - threading.Thread.start is patched out for every test, since
none of this source's logic needs a live socket to exercise: message
handling, staleness, and state selection are all plain method calls.
"""

import json
import time
from unittest.mock import patch

import pytest

from mediainfo.config import BrowserConfig
from mediainfo.sources.browser import BrowserSource


@pytest.fixture(autouse=True)
def no_real_server():
    with patch("threading.Thread.start", lambda self: None):
        yield


def _source(**kwargs) -> BrowserSource:
    defaults = dict(enabled=True)
    defaults.update(kwargs)
    return BrowserSource(BrowserConfig(**defaults))


def _event(**overrides):
    event = {
        "source": "browser",
        "site": "youtube",
        "state": "playing",
        "title": "Example title",
        "artist": "Example artist",
        "album": None,
        "media_type": "movie",
        "artwork_url": "https://example.com/thumb.jpg",
        "duration": 240,
        "progress": 42,
        "url": "https://youtube.com/watch?v=abc123",
        "timestamp": "2026-07-07T00:00:00Z",
    }
    event.update(overrides)
    return event


def test_no_events_returns_none():
    assert _source().get_now_playing() is None


def test_playing_event_is_surfaced():
    source = _source()
    source._handle_message(json.dumps(_event()))

    result = source.get_now_playing()

    assert result is not None
    assert result.source == "browser"
    assert result.title == "Example title"
    assert result.subtitle == "Example artist"
    assert result.artist == "Example artist"
    assert result.media_type == "movie"
    assert result.device == "Browser (youtube)"
    assert result.position_seconds == 42.0
    assert result.duration_seconds == 240.0
    assert result.images[0].url == "https://example.com/thumb.jpg"


def test_series_event_uses_kodi_style_title_and_subtitle():
    source = _source()
    source._handle_message(
        json.dumps(
            _event(
                site="plex",
                media_type="movie",  # deliberately "wrong" - series_title must win
                title="The Insider",
                series_title="The Boys",
                season=4,
                episode=7,
            )
        )
    )

    result = source.get_now_playing()

    assert result.media_type == "episode"
    assert result.title == "The Boys"
    assert result.subtitle == "S04E07 - The Insider"
    assert result.season == 4


def test_series_event_without_season_episode_uses_plain_subtitle():
    source = _source()
    source._handle_message(
        json.dumps(_event(site="svtplay", title="Avsnitt 3", series_title="Nyhetsmorgon"))
    )

    result = source.get_now_playing()

    assert result.media_type == "episode"
    assert result.title == "Nyhetsmorgon"
    assert result.subtitle == "Avsnitt 3"


def test_paused_event_is_not_surfaced():
    source = _source()
    source._handle_message(json.dumps(_event(state="paused")))

    assert source.get_now_playing() is None


def test_stopped_event_is_not_surfaced():
    source = _source()
    source._handle_message(json.dumps(_event(state="stopped")))

    assert source.get_now_playing() is None


def test_malformed_json_is_ignored_not_fatal():
    source = _source()
    source._handle_message("not json{{{")

    assert source.get_now_playing() is None


def test_non_object_json_is_ignored():
    source = _source()
    source._handle_message(json.dumps([1, 2, 3]))

    assert source.get_now_playing() is None


def test_event_without_url_or_site_is_ignored():
    source = _source()
    event = _event()
    del event["url"]
    del event["site"]
    source._handle_message(json.dumps(event))

    assert source.get_now_playing() is None


def test_multiple_tabs_prioritizes_playing_over_paused():
    source = _source()
    source._handle_message(json.dumps(_event(url="https://a", state="paused", title="A")))
    source._handle_message(json.dumps(_event(url="https://b", state="playing", title="B")))

    result = source.get_now_playing()

    assert result.title == "B"


def test_multiple_playing_tabs_picks_most_recently_updated():
    source = _source()
    source._handle_message(json.dumps(_event(url="https://a", state="playing", title="A")))
    source._handle_message(json.dumps(_event(url="https://b", state="playing", title="B")))

    result = source.get_now_playing()

    assert result.title == "B"


def test_same_url_overwrites_previous_entry():
    source = _source()
    source._handle_message(json.dumps(_event(url="https://a", title="First")))
    source._handle_message(json.dumps(_event(url="https://a", title="Second")))

    assert len(source._entries) == 1
    result = source.get_now_playing()
    assert result.title == "Second"


def test_stale_events_are_expired(monkeypatch):
    source = _source(timeout=5)
    source._handle_message(json.dumps(_event()))

    real_monotonic = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + 10)

    assert source.get_now_playing() is None
    assert source._entries == {}


def test_fresh_events_within_timeout_are_kept(monkeypatch):
    source = _source(timeout=30)
    source._handle_message(json.dumps(_event()))

    real_monotonic = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + 5)

    assert source.get_now_playing() is not None


def test_no_artwork_url_means_no_images():
    source = _source()
    source._handle_message(json.dumps(_event(artwork_url=None)))

    result = source.get_now_playing()
    assert result.images == []


def test_missing_progress_and_duration_are_none():
    source = _source()
    source._handle_message(json.dumps(_event(duration=None, progress=None)))

    result = source.get_now_playing()
    assert result.position_seconds is None
    assert result.duration_seconds is None


# ---------------------------------------------------------------------------
# Token authorization
# ---------------------------------------------------------------------------

def test_no_token_configured_authorizes_anything():
    source = _source(token="")
    assert source._is_authorized({}) is True
    assert source._is_authorized({"token": "whatever"}) is True


def test_matching_token_is_authorized():
    source = _source(token="secret123")
    assert source._is_authorized({"token": "secret123"}) is True


def test_missing_or_wrong_token_is_rejected():
    source = _source(token="secret123")
    assert source._is_authorized({}) is False
    assert source._is_authorized({"token": "wrong"}) is False


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

def test_config_disabled_by_default():
    assert BrowserConfig().enabled is False


def test_config_defaults():
    cfg = BrowserConfig()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8096
    assert cfg.token == ""
    assert cfg.timeout == 10.0
