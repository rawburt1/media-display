"""Tests for the TMDb rating enricher, and the pure module-level search/
image-url functions it shares with MediaDataStore (see
mediainfo/media_data_store.py's _fetch_movie_artwork/_fetch_series_artwork)."""

from unittest.mock import MagicMock, patch

from mediainfo.config import TmdbConfig
from mediainfo.enrichers.tmdb import TmdbEnricher, find_movie, find_tv, image_url
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
def test_skips_lookup_when_rating_already_set(mock_get):
    np = _movie()
    np.rating = 9.9  # e.g. already filled in by enrichers.omdb
    _enricher().enrich(np)
    mock_get.assert_not_called()
    assert np.rating == 9.9


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


# ---------------------------------------------------------------------------
# find_movie / find_tv / image_url - used by MediaDataStore, not by
# TmdbEnricher itself.
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.tmdb.requests.get")
def test_find_movie_prefers_result_matching_year(mock_get):
    mock_get.return_value = _response(json_data={"results": [
        {"id": 1, "release_date": "1985-01-01"},
        {"id": 2, "release_date": "1999-03-31"},
    ]})

    result = find_movie("test-key", "The Matrix", 1999)

    assert result == {"id": 2, "release_date": "1999-03-31"}


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_find_movie_falls_back_to_first_result_without_year_match(mock_get):
    mock_get.return_value = _response(json_data={"results": [
        {"id": 1, "release_date": "1985-01-01"},
    ]})

    result = find_movie("test-key", "The Matrix", 2010)

    assert result == {"id": 1, "release_date": "1985-01-01"}


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_find_movie_no_results_returns_none(mock_get):
    mock_get.return_value = _response(json_data={"results": []})

    assert find_movie("test-key", "Nonexistent Movie", None) is None


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_find_tv_takes_top_result_no_year_filter(mock_get):
    mock_get.return_value = _response(json_data={"results": [
        {"id": 1399, "first_air_date": "2011-04-17"},
    ]})

    result = find_tv("test-key", "Game of Thrones")

    assert result == {"id": 1399, "first_air_date": "2011-04-17"}
    url = mock_get.call_args[0][0]
    assert url.endswith("/search/tv")


def test_image_url_builds_cdn_url():
    assert image_url("/poster.jpg", "w500") == "https://image.tmdb.org/t/p/w500/poster.jpg"


def test_image_url_none_path_returns_none():
    assert image_url(None, "w500") is None


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------

def test_test_connection_success():
    with patch("mediainfo.enrichers.tmdb.fetch_rating", return_value=8.7):
        ok, message = _enricher().test_connection()
    assert ok is True
    assert "8.7" in message


def test_test_connection_failure():
    with patch("mediainfo.enrichers.tmdb.fetch_rating", return_value=None):
        ok, message = _enricher().test_connection()
    assert ok is False
    assert "api_key" in message


def test_test_connection_handles_exception():
    with patch("mediainfo.enrichers.tmdb.fetch_rating", side_effect=RuntimeError("boom")):
        ok, message = _enricher().test_connection()
    assert ok is False
    assert "boom" in message


# ---------------------------------------------------------------------------
# Cast fetching (enrichers.tmdb.fetch_cast) - fully independent of the
# rating logic above; every test here disables the rating half by
# pre-setting np.rating, so only the cast call is ever mocked/asserted on.
# ---------------------------------------------------------------------------

def _cast_enricher(fetch_cast=True, cast_size=8) -> TmdbEnricher:
    return TmdbEnricher(TmdbConfig(enabled=True, api_key="test-key", fetch_cast=fetch_cast, cast_size=cast_size))


_CREDITS_JSON = {
    "cast": [
        {"name": "Keanu Reeves", "character": "Neo", "profile_path": "/keanu.jpg"},
        {"name": "Laurence Fishburne", "character": "Morpheus", "profile_path": None},
        {"name": "", "character": "Uncredited", "profile_path": "/nobody.jpg"},
    ],
}


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_fetch_cast_disabled_by_default_leaves_cast_empty(mock_get):
    mock_get.return_value = _response(json_data={"vote_average": 8.0})
    np = _movie(ids={"tmdb": "603"})
    np.rating = 8.0  # skip the rating half entirely

    _cast_enricher(fetch_cast=False).enrich(np)

    mock_get.assert_not_called()
    assert np.cast == []


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_fetch_cast_via_known_tmdb_id_skips_search(mock_get):
    mock_get.return_value = _response(json_data=_CREDITS_JSON)
    np = _movie(ids={"tmdb": "603"})
    np.rating = 8.0

    _cast_enricher().enrich(np)

    url = mock_get.call_args[0][0]
    assert url.endswith("/movie/603/credits")
    assert np.cast == [
        {"name": "Keanu Reeves", "character": "Neo", "photo_url": "https://image.tmdb.org/t/p/h632/keanu.jpg"},
        {"name": "Laurence Fishburne", "character": "Morpheus", "photo_url": ""},
    ]


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_fetch_cast_skips_entries_with_no_name(mock_get):
    mock_get.return_value = _response(json_data=_CREDITS_JSON)
    np = _movie(ids={"tmdb": "603"})
    np.rating = 8.0

    _cast_enricher().enrich(np)

    assert all(member["name"] for member in np.cast)


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_fetch_cast_respects_cast_size_cap(mock_get):
    mock_get.return_value = _response(json_data=_CREDITS_JSON)
    np = _movie(ids={"tmdb": "603"})
    np.rating = 8.0

    _cast_enricher(cast_size=1).enrich(np)

    assert len(np.cast) == 1
    assert np.cast[0]["name"] == "Keanu Reeves"


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_fetch_cast_resolves_id_via_search_when_unknown(mock_get):
    def side_effect(url, **kwargs):
        if "/search/movie" in url:
            return _response(json_data={"results": [{"id": 603, "release_date": "1999-01-01"}]})
        assert url.endswith("/movie/603/credits")
        return _response(json_data=_CREDITS_JSON)

    mock_get.side_effect = side_effect
    np = _movie()  # no ids["tmdb"]
    np.rating = 8.0

    _cast_enricher().enrich(np)

    assert np.cast[0]["name"] == "Keanu Reeves"


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_fetch_cast_no_id_resolvable_returns_empty(mock_get):
    mock_get.return_value = _response(json_data={"results": []})
    np = _movie()
    np.rating = 8.0

    _cast_enricher().enrich(np)

    assert np.cast == []


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_fetch_cast_404_returns_empty(mock_get):
    mock_get.return_value = _response(status_code=404)
    np = _movie(ids={"tmdb": "603"})
    np.rating = 8.0

    _cast_enricher().enrich(np)

    assert np.cast == []


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_fetch_cast_network_error_returns_empty_not_raises(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")
    np = _movie(ids={"tmdb": "603"})
    np.rating = 8.0

    _cast_enricher().enrich(np)  # must not raise

    assert np.cast == []


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_fetch_cast_caches_by_id(mock_get):
    mock_get.return_value = _response(json_data=_CREDITS_JSON)
    enricher = _cast_enricher()

    enricher.enrich(_movie(ids={"tmdb": "603"}))
    np2 = _movie(ids={"tmdb": "603"})
    np2.rating = 8.0  # skip the rating half on the second call
    enricher.enrich(np2)

    # First enrich() call fetched both rating and credits (2 calls); the
    # second call's rating is pre-set (skipped) and its cast lookup hits
    # the cast cache - no further network calls.
    assert mock_get.call_count == 2


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_fetch_cast_skipped_when_already_populated(mock_get):
    np = _movie(ids={"tmdb": "603"})
    np.rating = 8.0
    np.cast = [{"name": "Already Set", "character": "", "photo_url": ""}]

    _cast_enricher().enrich(np)

    mock_get.assert_not_called()
    assert np.cast == [{"name": "Already Set", "character": "", "photo_url": ""}]


@patch("mediainfo.enrichers.tmdb.requests.get")
def test_fetch_cast_uses_tv_endpoint_for_episodes(mock_get):
    mock_get.return_value = _response(json_data=_CREDITS_JSON)
    np = _episode(ids={"tmdb": "1399"})
    np.rating = 9.0

    _cast_enricher().enrich(np)

    url = mock_get.call_args[0][0]
    assert url.endswith("/tv/1399/credits")


def test_fetch_cast_module_function_directly():
    from mediainfo.enrichers.tmdb import fetch_cast

    with patch("mediainfo.enrichers.tmdb.requests.get") as mock_get:
        mock_get.return_value = _response(json_data=_CREDITS_JSON)
        result = fetch_cast("test-key", "movie", "603", limit=8)

    assert result[0] == {
        "name": "Keanu Reeves", "character": "Neo",
        "photo_url": "https://image.tmdb.org/t/p/h632/keanu.jpg",
    }
