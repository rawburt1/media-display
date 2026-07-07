"""Tests for the Lidarr discography/album-art enricher."""

from typing import Any
from unittest.mock import MagicMock, patch

from mediainfo.config import LidarrConfig
from mediainfo.enrichers.lidarr import LidarrEnricher
from mediainfo.models import Artwork, NowPlaying


def _enricher(**kwargs) -> LidarrEnricher:
    defaults: dict[str, Any] = dict(enabled=True, host="192.168.1.50", port=8686, api_key="key123")
    defaults.update(kwargs)
    return LidarrEnricher(LidarrConfig(**defaults))


def _song(**kwargs) -> NowPlaying:
    defaults: dict[str, Any] = dict(
        source="kodi",
        media_type="music",
        title="Comfortably Numb",
        subtitle="Pink Floyd",
        album="The Wall",
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def _response(data):
    mock = MagicMock()
    mock.json.return_value = data
    mock.raise_for_status = MagicMock()
    return mock


_ARTISTS = [{"id": 1, "artistName": "Pink Floyd"}]
_ALBUMS = [
    {
        "id": 10,
        "title": "The Wall",
        "images": [{"coverType": "cover", "remoteUrl": "https://lidarr/wall.jpg"}],
    },
    {"id": 11, "title": "Animals", "images": []},
]
_TRACKS = [
    {"title": "Comfortably Numb", "albumId": 10},
    {"title": "Another Brick in the Wall", "albumId": 10},
    {"title": "Dogs", "albumId": 11},
]


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_matches_artist_and_sets_album_art_and_discography(mock_get):
    mock_get.side_effect = [_response(_ARTISTS), _response(_ALBUMS), _response(_TRACKS)]

    now_playing = _song()
    _enricher().enrich(now_playing)

    urls = [img.url for img in now_playing.images]
    assert "https://lidarr/wall.jpg" in urls
    assert "The Wall – Comfortably Numb" in now_playing.discography
    assert "The Wall – Another Brick in the Wall" in now_playing.discography
    assert "Animals – Dogs" in now_playing.discography

    artist_call = mock_get.call_args_list[0]
    assert artist_call.args[0] == "http://192.168.1.50:8686/api/v1/artist"
    assert artist_call.kwargs["headers"] == {"X-Api-Key": "key123"}

    album_call = mock_get.call_args_list[1]
    assert album_call.kwargs["params"] == {"artistId": 1}


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_no_artist_match_does_nothing(mock_get):
    mock_get.return_value = _response([])

    now_playing = _song()
    _enricher().enrich(now_playing)

    assert now_playing.images == []
    assert now_playing.discography == []


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_ignores_non_music_media_type(mock_get):
    now_playing = _song(media_type="movie")
    _enricher().enrich(now_playing)

    mock_get.assert_not_called()


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_without_subtitle_does_nothing(mock_get):
    now_playing = _song(subtitle="")
    _enricher().enrich(now_playing)

    mock_get.assert_not_called()


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_discography_capped_at_max_items(mock_get):
    many_tracks = [{"title": f"Track {i}", "albumId": 10} for i in range(10)]
    mock_get.side_effect = [_response(_ARTISTS), _response(_ALBUMS), _response(many_tracks)]

    now_playing = _song()
    _enricher(max_discography_items=3).enrich(now_playing)

    assert len(now_playing.discography) == 3


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_skips_duplicate_album_art_already_in_images(mock_get):
    mock_get.side_effect = [_response(_ARTISTS), _response(_ALBUMS), _response(_TRACKS)]

    now_playing = _song(images=[Artwork(url="https://lidarr/wall.jpg", label="Existing")])
    _enricher().enrich(now_playing)

    urls = [img.url for img in now_playing.images]
    assert urls.count("https://lidarr/wall.jpg") == 1


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_api_error_does_not_propagate(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")

    now_playing = _song()
    _enricher().enrich(now_playing)

    assert now_playing.images == []
    assert now_playing.discography == []


# ---------------------------------------------------------------------------
# test_connection (shared ArrEnricher implementation, with Lidarr's own
# _STATUS_PATH override - see also test_sonarr.py/test_radarr.py)
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.arr_base.requests.get")
def test_test_connection_success(mock_get):
    mock_get.return_value.raise_for_status = MagicMock()
    ok, message = _enricher().test_connection()
    assert ok is True
    args, kwargs = mock_get.call_args
    assert args[0] == "http://192.168.1.50:8686/api/v1/system/status"
    assert kwargs["headers"] == {"X-Api-Key": "key123"}


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_test_connection_handles_exception(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")
    ok, message = _enricher().test_connection()
    assert ok is False
    assert "connection refused" in message
