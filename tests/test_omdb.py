"""Tests for the OMDb (IMDb rating) enricher."""

from unittest.mock import MagicMock, patch

from mediainfo.config import OmdbConfig
from mediainfo.enrichers.omdb import OmdbEnricher
from mediainfo.models import NowPlaying


def _enricher() -> OmdbEnricher:
    return OmdbEnricher(OmdbConfig(enabled=True, api_key="test-key"))


def _movie(title="The Matrix", year=1999, ids=None):
    return NowPlaying(
        source="kodi", media_type="movie", title=title, year=year, ids=ids or {}
    )


def _episode(title="Breaking Bad", ids=None):
    return NowPlaying(source="kodi", media_type="episode", title=title, ids=ids or {})


def _response(json_data=None):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = json_data or {}
    return response


@patch("mediainfo.enrichers.omdb.requests.get")
def test_music_is_skipped(mock_get):
    np = NowPlaying(source="kodi", media_type="music", title="Song")
    _enricher().enrich(np)
    mock_get.assert_not_called()
    assert np.rating is None


@patch("mediainfo.enrichers.omdb.requests.get")
def test_skips_lookup_when_rating_already_set(mock_get):
    np = _movie()
    np.rating = 9.9  # e.g. already filled in by enrichers.tmdb
    _enricher().enrich(np)
    mock_get.assert_not_called()
    assert np.rating == 9.9


@patch("mediainfo.enrichers.omdb.requests.get")
def test_movie_title_search_sets_rating(mock_get):
    mock_get.return_value = _response({"Response": "True", "imdbRating": "8.7"})

    np = _movie()
    _enricher().enrich(np)

    assert np.rating == 8.7
    params = mock_get.call_args.kwargs["params"]
    assert params["t"] == "The Matrix"
    assert params["type"] == "movie"
    assert params["y"] == "1999"


@patch("mediainfo.enrichers.omdb.requests.get")
def test_episode_uses_series_type(mock_get):
    mock_get.return_value = _response({"Response": "True", "imdbRating": "9.5"})

    np = _episode()
    _enricher().enrich(np)

    assert np.rating == 9.5
    params = mock_get.call_args.kwargs["params"]
    assert params["type"] == "series"
    assert "y" not in params


@patch("mediainfo.enrichers.omdb.requests.get")
def test_direct_lookup_via_imdb_id_skips_title_search(mock_get):
    mock_get.return_value = _response({"Response": "True", "imdbRating": "8.7"})

    np = _movie(ids={"imdb": "tt0133093"})
    _enricher().enrich(np)

    assert np.rating == 8.7
    params = mock_get.call_args.kwargs["params"]
    assert params["i"] == "tt0133093"
    assert "t" not in params


@patch("mediainfo.enrichers.omdb.requests.get")
def test_not_found_response_leaves_rating_none(mock_get):
    mock_get.return_value = _response({"Response": "False", "Error": "Movie not found!"})

    np = _movie()
    _enricher().enrich(np)

    assert np.rating is None


@patch("mediainfo.enrichers.omdb.requests.get")
def test_na_rating_leaves_rating_none(mock_get):
    mock_get.return_value = _response({"Response": "True", "imdbRating": "N/A"})

    np = _movie()
    _enricher().enrich(np)

    assert np.rating is None


@patch("mediainfo.enrichers.omdb.requests.get")
def test_caches_lookup_by_id(mock_get):
    mock_get.return_value = _response({"Response": "True", "imdbRating": "8.7"})

    enricher = _enricher()
    enricher.enrich(_movie(ids={"imdb": "tt0133093"}))
    enricher.enrich(_movie(ids={"imdb": "tt0133093"}))

    mock_get.assert_called_once()


@patch("mediainfo.enrichers.omdb.requests.get")
def test_network_error_leaves_rating_none(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")

    np = _movie()
    _enricher().enrich(np)

    assert np.rating is None


@patch("mediainfo.enrichers.omdb.requests.get")
def test_api_key_sent_as_query_param(mock_get):
    mock_get.return_value = _response({"Response": "True", "imdbRating": "8.7"})

    OmdbEnricher(OmdbConfig(enabled=True, api_key="a473dd")).enrich(
        _movie(ids={"imdb": "tt0133093"})
    )

    params = mock_get.call_args.kwargs["params"]
    assert params["apikey"] == "a473dd"


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------

def test_test_connection_success():
    with patch.object(OmdbEnricher, "_fetch", return_value=8.7):
        ok, message = _enricher().test_connection()
    assert ok is True
    assert "8.7" in message


def test_test_connection_failure():
    with patch.object(OmdbEnricher, "_fetch", return_value=None):
        ok, message = _enricher().test_connection()
    assert ok is False
    assert "api_key" in message


def test_test_connection_handles_exception():
    with patch.object(OmdbEnricher, "_fetch", side_effect=RuntimeError("boom")):
        ok, message = _enricher().test_connection()
    assert ok is False
    assert "boom" in message
