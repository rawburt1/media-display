"""Tests for Jellyfin and Emby sources."""

from typing import Any
from unittest.mock import MagicMock, patch

from mediainfo.config import EmbyConfig, JellyfinConfig
from mediainfo.sources.jellyfin import EmbySource, JellyfinSource, _image_url, _parse_ids


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _jf(**kwargs) -> JellyfinSource:
    defaults: dict[str, Any] = dict(enabled=True, host="192.168.1.10", port=8096, api_key="jf-key")
    defaults.update(kwargs)
    return JellyfinSource(JellyfinConfig(**defaults))


def _emby(**kwargs) -> EmbySource:
    defaults: dict[str, Any] = dict(enabled=True, host="192.168.1.11", port=8096, api_key="emby-key")
    defaults.update(kwargs)
    return EmbySource(EmbyConfig(**defaults))


def _sessions(items):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = items
    return resp


def _playing(item):
    return [{"NowPlayingItem": item, "PlayState": {"IsPaused": False}}]


def _movie(**overrides):
    base = {
        "Type": "Movie",
        "Id": "movie1",
        "Name": "Inception",
        "ProductionYear": 2010,
        "ImageTags": {"Primary": "ptag"},
        "BackdropImageTags": ["btag"],
        "ProviderIds": {"Tmdb": "27205", "Imdb": "tt1375666"},
    }
    base.update(overrides)
    return base


def _episode(**overrides):
    base = {
        "Type": "Episode",
        "Id": "ep1",
        "Name": "Pilot",
        "SeriesName": "Breaking Bad",
        "SeriesId": "series1",
        "ParentIndexNumber": 1,
        "IndexNumber": 1,
        "SeriesPrimaryImageTag": "stag",
        "ParentBackdropItemId": "series1",
        "ParentBackdropImageTags": ["btag"],
        "ImageTags": {},
        "BackdropImageTags": [],
        "ProviderIds": {"Tvdb": "81189"},
    }
    base.update(overrides)
    return base


def _audio(**overrides):
    base = {
        "Type": "Audio",
        "Id": "track1",
        "Name": "Comfortably Numb",
        "AlbumArtist": "Pink Floyd",
        "Album": "The Wall",
        "AlbumId": "album1",
        "AlbumPrimaryImageTag": "atag",
        "ImageTags": {},
        "BackdropImageTags": [],
        "ProviderIds": {},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def test_image_url():
    url = _image_url("http://192.168.1.10:8096", "item1", "Primary", "key")
    assert url == "http://192.168.1.10:8096/Items/item1/Images/Primary?api_key=key"


def test_parse_ids_maps_known_providers():
    ids = _parse_ids({"Tmdb": "123", "Imdb": "tt456", "Tvdb": "789", "Unknown": "x"})
    assert ids == {"tmdb": "123", "imdb": "tt456", "tvdb": "789"}


def test_parse_ids_empty():
    assert _parse_ids({}) == {}
    assert _parse_ids(None) == {}


# ---------------------------------------------------------------------------
# Empty / paused / error
# ---------------------------------------------------------------------------

@patch("mediainfo.sources.jellyfin.requests.get")
def test_no_sessions_returns_none(mock_get):
    mock_get.return_value = _sessions([])
    assert _jf().get_now_playing() is None


@patch("mediainfo.sources.jellyfin.requests.get")
def test_session_without_now_playing_returns_none(mock_get):
    mock_get.return_value = _sessions([{"PlayState": {"IsPaused": False}}])
    assert _jf().get_now_playing() is None


@patch("mediainfo.sources.jellyfin.requests.get")
def test_paused_session_returns_none(mock_get):
    mock_get.return_value = _sessions(
        [{"NowPlayingItem": _movie(), "PlayState": {"IsPaused": True}}]
    )
    assert _jf().get_now_playing() is None


@patch("mediainfo.sources.jellyfin.requests.get")
def test_request_error_returns_none(mock_get):
    mock_get.side_effect = Exception("connection refused")
    source = _jf()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is True


@patch("mediainfo.sources.jellyfin.requests.get")
def test_calls_sessions_endpoint_with_api_key(mock_get):
    mock_get.return_value = _sessions([])
    _jf().get_now_playing()
    mock_get.assert_called_once_with(
        "http://192.168.1.10:8096/Sessions",
        params={"api_key": "jf-key"},
        timeout=5,
    )


# ---------------------------------------------------------------------------
# Movie
# ---------------------------------------------------------------------------

@patch("mediainfo.sources.jellyfin.requests.get")
def test_movie(mock_get):
    mock_get.return_value = _sessions(_playing(_movie()))
    np = _jf().get_now_playing()

    assert np.source == "jellyfin"
    assert np.media_type == "movie"
    assert np.title == "Inception"
    assert np.subtitle == ""
    assert np.year == 2010
    assert np.ids == {"tmdb": "27205", "imdb": "tt1375666"}
    assert len(np.images) == 2
    assert np.images[0].url == "http://192.168.1.10:8096/Items/movie1/Images/Primary?api_key=jf-key"
    assert np.images[0].label == "Poster (jellyfin)"
    assert np.images[1].url == "http://192.168.1.10:8096/Items/movie1/Images/Backdrop?api_key=jf-key"
    assert np.images[1].label == "Fanart (jellyfin)"


@patch("mediainfo.sources.jellyfin.requests.get")
def test_movie_without_backdrop(mock_get):
    mock_get.return_value = _sessions(_playing(_movie(BackdropImageTags=[])))
    np = _jf().get_now_playing()
    assert len(np.images) == 1
    assert np.images[0].label == "Poster (jellyfin)"


@patch("mediainfo.sources.jellyfin.requests.get")
def test_movie_without_any_images(mock_get):
    mock_get.return_value = _sessions(_playing(_movie(ImageTags={}, BackdropImageTags=[])))
    np = _jf().get_now_playing()
    assert np.images == []


# ---------------------------------------------------------------------------
# Episode
# ---------------------------------------------------------------------------

@patch("mediainfo.sources.jellyfin.requests.get")
def test_episode(mock_get):
    mock_get.return_value = _sessions(_playing(_episode()))
    np = _jf().get_now_playing()

    assert np.media_type == "episode"
    assert np.title == "Breaking Bad"
    assert np.subtitle == "S01E01 - Pilot"
    assert np.season == 1
    assert np.ids == {"tvdb": "81189"}
    assert len(np.images) == 2
    assert np.images[0].url == "http://192.168.1.10:8096/Items/series1/Images/Primary?api_key=jf-key"
    assert np.images[0].label == "Poster (jellyfin)"
    assert np.images[1].url == "http://192.168.1.10:8096/Items/series1/Images/Backdrop?api_key=jf-key"
    assert np.images[1].label == "Fanart (jellyfin)"


@patch("mediainfo.sources.jellyfin.requests.get")
def test_episode_falls_back_to_episode_primary_when_no_series_tag(mock_get):
    ep = _episode(SeriesPrimaryImageTag=None, ImageTags={"Primary": "eptag"})
    mock_get.return_value = _sessions(_playing(ep))
    np = _jf().get_now_playing()
    assert np.images[0].url == "http://192.168.1.10:8096/Items/ep1/Images/Primary?api_key=jf-key"


@patch("mediainfo.sources.jellyfin.requests.get")
def test_episode_falls_back_to_episode_backdrop(mock_get):
    ep = _episode(ParentBackdropItemId=None, ParentBackdropImageTags=[], BackdropImageTags=["ebtag"])
    mock_get.return_value = _sessions(_playing(ep))
    np = _jf().get_now_playing()
    assert np.images[1].url == "http://192.168.1.10:8096/Items/ep1/Images/Backdrop?api_key=jf-key"


@patch("mediainfo.sources.jellyfin.requests.get")
def test_episode_missing_season_episode_numbers(mock_get):
    ep = _episode(ParentIndexNumber=None, IndexNumber=None)
    mock_get.return_value = _sessions(_playing(ep))
    np = _jf().get_now_playing()
    assert np.subtitle == "Pilot"


# ---------------------------------------------------------------------------
# Audio / music
# ---------------------------------------------------------------------------

@patch("mediainfo.sources.jellyfin.requests.get")
def test_audio(mock_get):
    mock_get.return_value = _sessions(_playing(_audio()))
    np = _jf().get_now_playing()

    assert np.media_type == "music"
    assert np.title == "Comfortably Numb"
    assert np.subtitle == "Pink Floyd"
    assert len(np.images) == 1
    assert np.images[0].url == "http://192.168.1.10:8096/Items/album1/Images/Primary?api_key=jf-key"
    assert np.images[0].label == "Album art (jellyfin)"


@patch("mediainfo.sources.jellyfin.requests.get")
def test_audio_falls_back_to_track_image(mock_get):
    track = _audio(AlbumId=None, AlbumPrimaryImageTag=None, ImageTags={"Primary": "ttag"})
    mock_get.return_value = _sessions(_playing(track))
    np = _jf().get_now_playing()
    assert np.images[0].url == "http://192.168.1.10:8096/Items/track1/Images/Primary?api_key=jf-key"


@patch("mediainfo.sources.jellyfin.requests.get")
def test_audio_no_images(mock_get):
    track = _audio(AlbumId=None, AlbumPrimaryImageTag=None, ImageTags={})
    mock_get.return_value = _sessions(_playing(track))
    np = _jf().get_now_playing()
    assert np.images == []


@patch("mediainfo.sources.jellyfin.requests.get")
def test_audio_falls_back_to_artists_list_for_subtitle(mock_get):
    track = _audio(AlbumArtist="", Artists=["David Gilmour"])
    mock_get.return_value = _sessions(_playing(track))
    np = _jf().get_now_playing()
    assert np.subtitle == "David Gilmour"


# ---------------------------------------------------------------------------
# Unknown media type falls back to music/audio path
# ---------------------------------------------------------------------------

@patch("mediainfo.sources.jellyfin.requests.get")
def test_unknown_type_treated_as_audio(mock_get):
    item = {**_audio(), "Type": "MusicVideo"}
    mock_get.return_value = _sessions(_playing(item))
    np = _jf().get_now_playing()
    assert np.media_type == "music"


# ---------------------------------------------------------------------------
# Emby — same logic, separate name and base URL
# ---------------------------------------------------------------------------

@patch("mediainfo.sources.jellyfin.requests.get")
def test_emby_movie(mock_get):
    mock_get.return_value = _sessions(_playing(_movie()))
    np = _emby().get_now_playing()

    assert np.source == "emby"
    assert np.title == "Inception"
    assert np.images[0].url == "http://192.168.1.11:8096/Items/movie1/Images/Primary?api_key=emby-key"
    assert np.images[0].label == "Poster (emby)"


@patch("mediainfo.sources.jellyfin.requests.get")
def test_emby_calls_correct_host(mock_get):
    mock_get.return_value = _sessions([])
    _emby().get_now_playing()
    mock_get.assert_called_once_with(
        "http://192.168.1.11:8096/Sessions",
        params={"api_key": "emby-key"},
        timeout=5,
    )


# ---------------------------------------------------------------------------
# First active session wins when multiple sessions exist
# ---------------------------------------------------------------------------

@patch("mediainfo.sources.jellyfin.requests.get")
def test_first_non_paused_session_wins(mock_get):
    sessions = [
        {"NowPlayingItem": _movie(Name="Paused Film"), "PlayState": {"IsPaused": True}},
        {"NowPlayingItem": _movie(Name="Playing Film"), "PlayState": {"IsPaused": False}},
    ]
    mock_get.return_value = _sessions(sessions)
    np = _jf().get_now_playing()
    assert np.title == "Playing Film"
