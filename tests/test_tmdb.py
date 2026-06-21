"""Tests for the TMDb rating enricher."""

from unittest.mock import MagicMock, patch

from mediainfo.config import TmdbConfig
from mediainfo.enrichers.tmdb import TmdbEnricher
from mediainfo.models import NowPlaying


def _enricher() -> TmdbEnricher:
    return TmdbEnricher(TmdbConfig(enabled=True, api_key="test-key"))


def _movie(title="The Matrix", year=1999, ids=None):
    return NowPlaying(
        source="kodi", media_type="movie", title=title, year=year, ids=ids or {}
    )


def _episode(title="Breaking Bad", ids=None):
    return NowPlaying(source="kodi", media_type="episode", title=title, ids=ids or {})


def _response(status_code=200, json_data=None):
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    response.json.return_value = json_data or {}
    return response


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_music_is_skipped(mock_get):
    np = NowPlaying(source="kodi", media_type="music", title="Song")
    _enricher().enrich(np)
    mock_get.assert_not_called()
    assert np.rating is None


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_movie_search_sets_rating(mock_get):
    mock_get.return_value = _response(
        json_data={"results": [{"vote_average": 8.456}]}
    )

    np = _movie()
    _enricher().enrich(np)

    assert np.rating == 8.5
    url = mock_get.call_args[0][0]
    assert url.endswith("/search/movie")


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_episode_uses_tv_search(mock_get):
    mock_get.return_value = _response(json_data={"results": [{"vote_average": 9.0}]})

    np = _episode()
    _enricher().enrich(np)

    assert np.rating == 9.0
    url = mock_get.call_args[0][0]
    assert url.endswith("/search/tv")


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_direct_lookup_via_tmdb_id_skips_search(mock_get):
    mock_get.return_value = _response(json_data={"vote_average": 7.7})

    np = _movie(ids={"tmdb": "603"})
    _enricher().enrich(np)

    assert np.rating == 7.7
    url = mock_get.call_args[0][0]
    assert url.endswith("/movie/603")


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_no_results_leaves_rating_none(mock_get):
    mock_get.return_value = _response(json_data={"results": []})

    np = _movie()
    _enricher().enrich(np)

    assert np.rating is None


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_caches_lookup_by_id(mock_get):
    mock_get.return_value = _response(json_data={"vote_average": 7.7})

    enricher = _enricher()
    enricher.enrich(_movie(ids={"tmdb": "603"}))
    enricher.enrich(_movie(ids={"tmdb": "603"}))

    mock_get.assert_called_once()


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_network_error_leaves_rating_none(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")

    np = _movie()
    _enricher().enrich(np)

    assert np.rating is None


# ---------------------------------------------------------------------------
# Auth: v3 api_key (query param) vs v4 API Read Access Token (Bearer header)
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.tmdb.requests.get")
def test_v3_api_key_sent_as_query_param(mock_get):
    mock_get.return_value = _response(json_data={"vote_average": 8.0})
    enricher = TmdbEnricher(TmdbConfig(enabled=True, api_key="abcd1234"))

    enricher.enrich(_movie(ids={"tmdb": "603"}))

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["api_key"] == "abcd1234"
    assert "headers" not in kwargs


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_v4_jwt_token_sent_as_bearer_header(mock_get):
    mock_get.return_value = _response(json_data={"vote_average": 8.0})
    jwt_token = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJ4eXoifQ.signature"
    enricher = TmdbEnricher(TmdbConfig(enabled=True, api_key=jwt_token))

    enricher.enrich(_movie(ids={"tmdb": "603"}))

    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["Authorization"] == f"Bearer {jwt_token}"
    assert "api_key" not in (kwargs.get("params") or {})
