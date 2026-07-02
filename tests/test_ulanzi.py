"""Tests for the Ulanzi TC001 (AWTRIX3) text output."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mediainfo.config import UlanziConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.ulanzi import UlanziOutput


def _output(**kwargs) -> UlanziOutput:
    defaults = dict(enabled=True, device_ip="192.168.1.30", app_name="now_playing")
    defaults.update(kwargs)
    return UlanziOutput(UlanziConfig(**defaults))


@patch("mediainfo.outputs.ulanzi.requests.post")
def test_music_sends_artist_and_song(mock_post):
    now_playing = NowPlaying(
        source="kodi", media_type="music", title="Comfortably Numb", subtitle="Pink Floyd"
    )

    _output().on_new_item(now_playing, MagicMock())

    args, kwargs = mock_post.call_args
    assert args[0] == "http://192.168.1.30/api/custom"
    assert kwargs["params"] == {"name": "now_playing"}
    assert kwargs["json"] == {"text": "Pink Floyd - Comfortably Numb", "textCase": 2}


@pytest.mark.parametrize(
    "title",
    [
        "Comfortably Numb - 2011 Remastered Version",
        "Comfortably Numb (2011 Remaster)",
        "Comfortably Numb [Remastered]",
        "Comfortably Numb - Remix",
        "Comfortably Numb (Live)",
        "Comfortably Numb - Live at Pompeii",
        "Comfortably Numb (Radio Edit)",
        "Comfortably Numb - Deluxe Edition",
        "Comfortably Numb (Single Version)",
        "Comfortably Numb - Demo",
        "Comfortably Numb (Alternate Take)",
        "Comfortably Numb - Newly Remastered",
    ],
)
@patch("mediainfo.outputs.ulanzi.requests.post")
def test_music_strips_version_suffix_from_title(mock_post, title):
    now_playing = NowPlaying(source="kodi", media_type="music", title=title, subtitle="Pink Floyd")

    _output().on_new_item(now_playing, MagicMock())

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["text"] == "Pink Floyd - Comfortably Numb"


@patch("mediainfo.outputs.ulanzi.requests.post")
def test_music_keeps_unrelated_parenthetical(mock_post):
    now_playing = NowPlaying(
        source="kodi",
        media_type="music",
        title="Shine On You Crazy Diamond (Parts I-V)",
        subtitle="Pink Floyd",
    )

    _output().on_new_item(now_playing, MagicMock())

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["text"] == "Pink Floyd - Shine On You Crazy Diamond (Parts I-V)"


@patch("mediainfo.outputs.ulanzi.requests.post")
def test_movie_sends_title_and_year(mock_post):
    now_playing = NowPlaying(
        source="kodi", media_type="movie", title="Inception", subtitle="", year=2010
    )

    _output().on_new_item(now_playing, MagicMock())

    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"text": "Inception (2010)", "textCase": 2}


@patch("mediainfo.outputs.ulanzi.requests.post")
def test_movie_without_year_sends_title_only(mock_post):
    now_playing = NowPlaying(source="kodi", media_type="movie", title="Inception", subtitle="")

    _output().on_new_item(now_playing, MagicMock())

    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"text": "Inception", "textCase": 2}


@patch("mediainfo.outputs.ulanzi.requests.post")
def test_episode_sends_show_and_lowercase_season_episode_code(mock_post):
    now_playing = NowPlaying(
        source="kodi",
        media_type="episode",
        title="Breaking Bad",
        subtitle="S01E01 - Pilot",
        season=1,
    )

    _output().on_new_item(now_playing, MagicMock())

    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"text": "Breaking Bad s01e01", "textCase": 2}


@patch("mediainfo.outputs.ulanzi.requests.post")
def test_episode_with_unrecognized_subtitle_falls_back(mock_post):
    now_playing = NowPlaying(
        source="kodi", media_type="episode", title="Breaking Bad", subtitle="Pilot"
    )

    _output().on_new_item(now_playing, MagicMock())

    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"text": "Breaking Bad - Pilot", "textCase": 2}


@patch("mediainfo.outputs.ulanzi.requests.post")
def test_on_idle_clears_custom_app(mock_post):
    output = _output()
    output._last_text = "Pink Floyd - Comfortably Numb"

    output.on_idle()

    args, kwargs = mock_post.call_args
    assert args[0] == "http://192.168.1.30/api/custom"
    assert kwargs["params"] == {"name": "now_playing"}
    assert kwargs["data"] == b""
    assert "json" not in kwargs


@patch("mediainfo.outputs.ulanzi.requests.post")
def test_idle_wallpaper_update_clears_custom_app(mock_post):
    output = _output()
    output._last_text = "Pink Floyd - Comfortably Numb"

    idle_now_playing = NowPlaying(source="idle", media_type="wallpaper", title="", subtitle="")
    output.update(idle_now_playing, Artwork(url="https://example.com/wallpaper.jpg"), Path("/tmp/w.jpg"))

    _, kwargs = mock_post.call_args
    assert kwargs["data"] == b""


@patch("mediainfo.outputs.ulanzi.requests.post")
def test_unchanged_text_is_not_resent(mock_post):
    output = _output()
    now_playing = NowPlaying(
        source="kodi", media_type="music", title="Comfortably Numb", subtitle="Pink Floyd"
    )

    output.on_new_item(now_playing, MagicMock())
    output.on_new_item(now_playing, MagicMock())

    assert mock_post.call_count == 1


@patch("mediainfo.outputs.ulanzi.requests.post")
def test_repeated_idle_does_not_resend(mock_post):
    output = _output()
    output._last_text = "Pink Floyd - Comfortably Numb"

    output.on_idle()
    output.on_idle()

    assert mock_post.call_count == 1


@patch("mediainfo.outputs.ulanzi.requests.post")
def test_uses_configured_app_name_and_basic_auth(mock_post):
    output = _output(app_name="my_app", username="user", password="pass")
    now_playing = NowPlaying(
        source="kodi", media_type="music", title="Comfortably Numb", subtitle="Pink Floyd"
    )

    output.on_new_item(now_playing, MagicMock())

    _, kwargs = mock_post.call_args
    assert kwargs["params"] == {"name": "my_app"}
    assert kwargs["auth"] == ("user", "pass")


@patch("mediainfo.outputs.ulanzi.requests.post")
def test_request_error_is_caught(mock_post):
    mock_post.side_effect = Exception("boom")
    now_playing = NowPlaying(
        source="kodi", media_type="music", title="Comfortably Numb", subtitle="Pink Floyd"
    )

    _output().on_new_item(now_playing, MagicMock())


# ---------------------------------------------------------------------------
# Power/brightness scheduling (see display_schedule.py)
# ---------------------------------------------------------------------------

@patch("mediainfo.outputs.ulanzi.requests.post")
def test_schedule_tick_without_schedule_sends_nothing(mock_post):
    output = _output()
    output.on_schedule_tick()
    mock_post.assert_not_called()


@patch("mediainfo.outputs.ulanzi.requests.post")
def test_schedule_tick_drives_power_and_brightness_endpoints(mock_post):
    import datetime

    output = _output(screen_off_hours="23:00-07:00", brightness_schedule=["20:00-23:00=10"])
    output._scheduler.tick(datetime.time(21, 0))

    calls = {call.args[0]: call.kwargs.get("json") for call in mock_post.call_args_list}
    assert calls["http://192.168.1.30/api/settings"] == {"BRI": 10}
    assert calls["http://192.168.1.30/api/power"] == {"power": True}

    mock_post.reset_mock()
    output._scheduler.tick(datetime.time(23, 30))
    assert mock_post.call_args.args[0] == "http://192.168.1.30/api/power"
    assert mock_post.call_args.kwargs["json"] == {"power": False}
