"""Tests for the generic Chromecast/Cast "now playing" source."""

from unittest.mock import MagicMock, patch

from mediainfo.config import ChromecastConfig
from mediainfo.sources.chromecast import ChromecastSource


def _source(**kwargs) -> ChromecastSource:
    defaults = dict(enabled=True, device_ips=["192.168.1.90"])
    defaults.update(kwargs)
    return ChromecastSource(ChromecastConfig(**defaults))


def _status(
    player_state="PLAYING",
    metadata_type=0,
    title=None,
    artist=None,
    album_name=None,
    series_title=None,
    season=None,
    episode=None,
    images=None,
):
    status = MagicMock()
    status.player_state = player_state
    status.media_is_musictrack = metadata_type == 3
    status.media_is_tvshow = metadata_type == 2
    status.title = title
    status.artist = artist
    status.album_name = album_name
    status.series_title = series_title
    status.season = season
    status.episode = episode
    status.images = images or []
    return status


def _cast(status, app_display_name="YouTube"):
    cast = MagicMock()
    cast.app_display_name = app_display_name
    cast.media_controller.status = status
    return cast


@patch("mediainfo.sources.chromecast.pychromecast.get_chromecast_from_host")
def test_connects_to_each_configured_ip_once(mock_connect):
    cast = _cast(_status(player_state="IDLE"))
    mock_connect.return_value = cast

    source = _source()
    source.get_now_playing()
    source.get_now_playing()

    mock_connect.assert_called_once()


@patch("mediainfo.sources.chromecast.pychromecast.get_chromecast_from_host")
def test_returns_none_when_not_playing(mock_connect):
    mock_connect.return_value = _cast(_status(player_state="IDLE"))
    assert _source().get_now_playing() is None


@patch("mediainfo.sources.chromecast.pychromecast.get_chromecast_from_host")
def test_returns_none_for_ignored_app(mock_connect):
    mock_connect.return_value = _cast(_status(), app_display_name="Backdrop")
    assert _source().get_now_playing() is None


@patch("mediainfo.sources.chromecast.pychromecast.get_chromecast_from_host")
def test_music_track(mock_connect):
    mock_connect.return_value = _cast(
        _status(metadata_type=3, title="Comfortably Numb", artist="Pink Floyd", album_name="The Wall")
    )

    now_playing = _source().get_now_playing()

    assert now_playing.media_type == "music"
    assert now_playing.title == "Comfortably Numb"
    assert now_playing.subtitle == "Pink Floyd"
    assert now_playing.album == "The Wall"


@patch("mediainfo.sources.chromecast.pychromecast.get_chromecast_from_host")
def test_tv_episode_with_season_and_episode(mock_connect):
    mock_connect.return_value = _cast(
        _status(metadata_type=2, title="Pilot", series_title="Breaking Bad", season=1, episode=1)
    )

    now_playing = _source().get_now_playing()

    assert now_playing.media_type == "episode"
    assert now_playing.title == "Breaking Bad"
    assert now_playing.subtitle == "S01E01 - Pilot"
    assert now_playing.season == 1


@patch("mediainfo.sources.chromecast.pychromecast.get_chromecast_from_host")
def test_generic_media_falls_back_to_movie_with_app_name(mock_connect):
    mock_connect.return_value = _cast(
        _status(metadata_type=0, title="Some Show"), app_display_name="Netflix"
    )

    now_playing = _source().get_now_playing()

    assert now_playing.media_type == "movie"
    assert now_playing.title == "Some Show"
    assert now_playing.subtitle == "Netflix"


@patch("mediainfo.sources.chromecast.pychromecast.get_chromecast_from_host")
def test_includes_artwork_image(mock_connect):
    image = MagicMock()
    image.url = "https://example.com/art.jpg"
    mock_connect.return_value = _cast(
        _status(metadata_type=3, title="Song", artist="Artist", images=[image])
    )

    now_playing = _source().get_now_playing()

    assert now_playing.images[0].url == "https://example.com/art.jpg"


@patch("mediainfo.sources.chromecast.pychromecast.get_chromecast_from_host")
def test_unreachable_device_sets_last_poll_failed(mock_connect):
    mock_connect.side_effect = RuntimeError("connection refused")

    source = _source()
    result = source.get_now_playing()

    assert result is None
    assert source.last_poll_failed is True


def test_no_device_ips_configured_never_fails():
    source = _source(device_ips=[])
    assert source.get_now_playing() is None
    assert source.last_poll_failed is False
