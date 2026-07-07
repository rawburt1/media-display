"""Tests for the Radarr artwork/studio/genres enricher."""

from typing import Any
from unittest.mock import MagicMock, patch

from mediainfo.config import RadarrConfig
from mediainfo.enrichers.radarr import RadarrEnricher
from mediainfo.models import Artwork, NowPlaying


def _enricher() -> RadarrEnricher:
    return RadarrEnricher(RadarrConfig(enabled=True, host="192.168.1.50", port=7878, api_key="key123"))


def _movie_now_playing(**kwargs) -> NowPlaying:
    defaults: dict[str, Any] = dict(
        source="kodi",
        media_type="movie",
        title="The Matrix",
        ids={"tmdb": "603"},
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def _movie(**kwargs) -> dict:
    defaults = {
        "title": "The Matrix",
        "studio": "Warner Bros.",
        "genres": ["Action", "Science Fiction"],
        "images": [
            {"coverType": "poster", "remoteUrl": "https://radarr/poster.jpg"},
            {"coverType": "fanart", "remoteUrl": "https://radarr/fanart.jpg"},
        ],
    }
    defaults.update(kwargs)
    return defaults


def _response(data):
    mock = MagicMock()
    mock.json.return_value = data
    mock.raise_for_status = MagicMock()
    return mock


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_matches_by_tmdb_id_and_sets_studio_genres_and_images(mock_get):
    mock_get.return_value = _response([_movie()])

    now_playing = _movie_now_playing()
    _enricher().enrich(now_playing)

    assert now_playing.studio == "Warner Bros."
    assert now_playing.genres == ["Action", "Science Fiction"]
    urls = [img.url for img in now_playing.images]
    assert "https://radarr/poster.jpg" in urls
    assert "https://radarr/fanart.jpg" in urls

    args, kwargs = mock_get.call_args
    assert args[0] == "http://192.168.1.50:7878/api/v3/movie"
    assert kwargs["params"] == {"tmdbId": "603"}
    assert kwargs["headers"] == {"X-Api-Key": "key123"}


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_falls_back_to_title_match_without_tmdb_id(mock_get):
    mock_get.return_value = _response([_movie(title="Other Movie"), _movie()])

    now_playing = _movie_now_playing(ids={})
    _enricher().enrich(now_playing)

    assert now_playing.studio == "Warner Bros."


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_no_match_does_nothing(mock_get):
    mock_get.return_value = _response([])

    now_playing = _movie_now_playing()
    _enricher().enrich(now_playing)

    assert now_playing.studio == ""
    assert now_playing.genres == []
    assert now_playing.images == []


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_ignores_non_movie_media_type(mock_get):
    now_playing = _movie_now_playing(media_type="episode")
    _enricher().enrich(now_playing)

    mock_get.assert_not_called()


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_skips_duplicate_already_in_images(mock_get):
    mock_get.return_value = _response([_movie()])

    now_playing = _movie_now_playing(
        images=[Artwork(url="https://radarr/poster.jpg", label="Existing")]
    )
    _enricher().enrich(now_playing)

    urls = [img.url for img in now_playing.images]
    assert urls.count("https://radarr/poster.jpg") == 1


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_does_not_overwrite_existing_genres_and_studio(mock_get):
    mock_get.return_value = _response([_movie()])

    now_playing = _movie_now_playing(studio="Existing Studio", genres=["Drama"])
    _enricher().enrich(now_playing)

    assert now_playing.studio == "Existing Studio"
    assert now_playing.genres == ["Drama"]


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_api_error_does_not_propagate(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")

    now_playing = _movie_now_playing()
    _enricher().enrich(now_playing)

    assert now_playing.images == []


# ---------------------------------------------------------------------------
# test_connection (shared ArrEnricher implementation - see also
# test_sonarr.py/test_lidarr.py for the same coverage on the other two)
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.arr_base.requests.get")
def test_test_connection_success(mock_get):
    mock_get.return_value.raise_for_status = MagicMock()
    ok, message = _enricher().test_connection()
    assert ok is True
    args, kwargs = mock_get.call_args
    assert args[0] == "http://192.168.1.50:7878/api/v3/system/status"
    assert kwargs["headers"] == {"X-Api-Key": "key123"}


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_test_connection_handles_exception(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")
    ok, message = _enricher().test_connection()
    assert ok is False
    assert "connection refused" in message
