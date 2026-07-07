"""Tests for the thetvdb.com enricher."""

from typing import Any
from unittest.mock import MagicMock, patch

from mediainfo.config import TheTvDbConfig
from mediainfo.enrichers.thetvdb import TheTvDbEnricher
from mediainfo.models import Artwork, NowPlaying

_ARTWORK_TYPES = {
    "data": [
        {"id": 2, "name": "Poster", "recordType": "series"},
        {"id": 3, "name": "Background", "recordType": "series"},
        {"id": 14, "name": "Poster", "recordType": "season"},
    ]
}

_SERIES_ARTWORKS = {
    "data": {
        "artworks": [
            {"type": 2, "image": "https://thetvdb.com/poster-low.jpg", "score": 10},
            {"type": 2, "image": "https://thetvdb.com/poster-high.jpg", "score": 99},
            {"type": 3, "image": "https://thetvdb.com/background.jpg", "score": 50},
            {"type": 14, "image": "https://thetvdb.com/season-poster.jpg", "score": 100},
        ]
    }
}


def _enricher(**kwargs) -> TheTvDbEnricher:
    defaults: dict[str, Any] = dict(enabled=True, api_key="test-key", pin="")
    defaults.update(kwargs)
    return TheTvDbEnricher(TheTvDbConfig(**defaults))


def _now_playing(**kwargs) -> NowPlaying:
    defaults: dict[str, Any] = dict(source="kodi", media_type="episode", title="Pilot", subtitle="S01E01")
    defaults.update(kwargs)
    return NowPlaying(**defaults, ids={"tvdb": "12345"})


def _response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        response.raise_for_status = MagicMock()
    return response


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_adds_poster_and_fanart(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [_response(_ARTWORK_TYPES), _response(_SERIES_ARTWORKS)]

    now_playing = _now_playing()
    _enricher().enrich(now_playing)

    assert [(i.label, i.url) for i in now_playing.images] == [
        ("Poster (TheTVDB)", "https://thetvdb.com/poster-high.jpg"),
        ("Fanart (TheTVDB)", "https://thetvdb.com/background.jpg"),
    ]

    # Logged in with the configured api key.
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"apikey": "test-key"}


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_skips_non_episode(mock_post, mock_get):
    now_playing = _now_playing(media_type="movie", subtitle="")

    _enricher().enrich(now_playing)

    mock_post.assert_not_called()
    mock_get.assert_not_called()
    assert now_playing.images == []


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_no_tvdb_id_and_no_title_skips(mock_post, mock_get):
    now_playing = NowPlaying(
        source="shield", media_type="episode", title="", subtitle="", ids={}
    )

    _enricher().enrich(now_playing)

    mock_post.assert_not_called()
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Title-based fallback (for sources with no tvdb id, e.g. the Shield source)
# ---------------------------------------------------------------------------

_SEARCH_RESULTS = {"data": [{"tvdb_id": "98765", "name": "Kingdom", "type": "series"}]}


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_resolves_series_id_by_title_when_no_tvdb_id(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [
        _response(_SEARCH_RESULTS),
        _response(_ARTWORK_TYPES),
        _response(_SERIES_ARTWORKS),
    ]

    now_playing = NowPlaying(
        source="shield", media_type="episode", title="Kingdom",
        subtitle="5. När makten skiftar", ids={},
    )
    _enricher().enrich(now_playing)

    assert now_playing.ids["tvdb"] == "98765"
    assert len(now_playing.images) == 2

    search_args, search_kwargs = mock_get.call_args_list[0]
    assert search_args[0] == "https://api4.thetvdb.com/v4/search"
    assert search_kwargs["params"] == {"query": "Kingdom", "type": "series"}


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_series_id_resolution_is_cached_across_calls(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [
        _response(_SEARCH_RESULTS),
        _response(_ARTWORK_TYPES),
        _response(_SERIES_ARTWORKS),
        _response(_SERIES_ARTWORKS),
    ]

    enricher = _enricher()
    np1 = NowPlaying(source="shield", media_type="episode", title="Kingdom", ids={})
    enricher.enrich(np1)
    search_calls_after_first = mock_get.call_count

    np2 = NowPlaying(source="shield", media_type="episode", title="Kingdom", ids={})
    enricher.enrich(np2)

    assert np2.ids["tvdb"] == "98765"
    # Only one more call (artworks) - no repeat /search call for the same title.
    assert mock_get.call_count == search_calls_after_first + 1


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_series_search_no_results_skips(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.return_value = _response({"data": []})

    now_playing = NowPlaying(
        source="shield", media_type="episode", title="Some Unknown Show", ids={}
    )
    _enricher().enrich(now_playing)

    assert now_playing.images == []
    assert "tvdb" not in now_playing.ids


# ---------------------------------------------------------------------------
# Disambiguating same-titled shows by episode (e.g. several "Kingdom"s)
# ---------------------------------------------------------------------------

_AMBIGUOUS_RESULTS = {
    "data": [
        {"tvdb_id": "111", "name": "Kingdom", "type": "series"},
        {"tvdb_id": "222", "name": "Kingdom", "type": "series"},
    ]
}


def _episodes(*names):
    return {"data": {"episodes": [{"name": n} for n in names]}}


def _kingdom_now_playing(subtitle="5. När makten skiftar") -> NowPlaying:
    return NowPlaying(
        source="shield", media_type="episode", title="Kingdom", subtitle=subtitle, ids={}
    )


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_disambiguates_multiple_candidates_by_episode_name(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [
        _response(_AMBIGUOUS_RESULTS),
        _response(_episodes("Some Other Episode")),       # candidate 111: no match
        _response(_episodes("När makten skiftar")),        # candidate 222: match
        _response(_ARTWORK_TYPES),
        _response(_SERIES_ARTWORKS),
    ]

    now_playing = _kingdom_now_playing()
    _enricher().enrich(now_playing)

    assert now_playing.ids["tvdb"] == "222"
    assert len(now_playing.images) == 2


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_disambiguates_using_swedish_translation_when_default_name_does_not_match(
    mock_post, mock_get
):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [
        _response(_AMBIGUOUS_RESULTS),
        _response(_episodes("Episode One")),               # 111 default: no match
        _response(_episodes("Episode Five")),               # 222 default: no match
        _response(_episodes("Avsnitt ett")),                # 111 swedish: no match
        _response(_episodes("När makten skiftar")),         # 222 swedish: match
        _response(_ARTWORK_TYPES),
        _response(_SERIES_ARTWORKS),
    ]

    now_playing = _kingdom_now_playing()
    _enricher().enrich(now_playing)

    assert now_playing.ids["tvdb"] == "222"
    # Second-to-last and 4th-to-last calls used the Swedish lang param.
    swedish_call = mock_get.call_args_list[4]
    assert swedish_call.kwargs["params"] == {"lang": "swe"}


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_no_candidate_verified_returns_no_artwork(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [
        _response(_AMBIGUOUS_RESULTS),
        _response(_episodes("Episode One")),
        _response(_episodes("Episode Five")),
        _response(_episodes("Avsnitt ett")),
        _response(_episodes("Avsnitt fem")),
    ]

    now_playing = _kingdom_now_playing()
    _enricher().enrich(now_playing)

    assert now_playing.images == []
    assert "tvdb" not in now_playing.ids


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_subtitle_without_episode_number_prefix_skips_disambiguation(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.return_value = _response(_AMBIGUOUS_RESULTS)

    now_playing = _kingdom_now_playing(subtitle="S01E05")  # no "N. " prefix
    _enricher().enrich(now_playing)

    assert now_playing.images == []
    assert "tvdb" not in now_playing.ids
    # Only the /search call - no episode lists fetched for unverifiable subtitle.
    assert mock_get.call_count == 1


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_single_search_result_is_trusted_without_disambiguation(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [
        _response(_SEARCH_RESULTS),  # one result only
        _response(_ARTWORK_TYPES),
        _response(_SERIES_ARTWORKS),
    ]

    now_playing = _kingdom_now_playing()
    _enricher().enrich(now_playing)

    assert now_playing.ids["tvdb"] == "98765"
    assert len(now_playing.images) == 2


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_search_candidates_are_capped(mock_post, mock_get):
    many_results = {
        "data": [{"tvdb_id": str(i), "name": "Kingdom", "type": "series"} for i in range(10)]
    }
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [_response(many_results)] + [
        _response(_episodes("No match here")) for _ in range(10)
    ]

    now_playing = _kingdom_now_playing()
    _enricher().enrich(now_playing)

    # 1 search call + at most 5 candidates x 2 languages = 11 calls max.
    assert mock_get.call_count <= 11
    assert now_playing.images == []


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_search_candidate_cap_is_configurable(mock_post, mock_get):
    many_results = {
        "data": [{"tvdb_id": str(i), "name": "Kingdom", "type": "series"} for i in range(10)]
    }
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [_response(many_results)] + [
        _response(_episodes("No match here")) for _ in range(20)
    ]

    now_playing = _kingdom_now_playing()
    _enricher(max_search_candidates=2).enrich(now_playing)

    # 1 search call + at most 2 candidates x 2 languages = 5 calls max.
    assert mock_get.call_count <= 5


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_logs_when_no_candidate_can_be_verified(mock_post, mock_get, caplog):
    import logging

    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [
        _response(_AMBIGUOUS_RESULTS),
        _response(_episodes("Episode One")),
        _response(_episodes("Episode Five")),
        _response(_episodes("Avsnitt ett")),
        _response(_episodes("Avsnitt fem")),
    ]

    with caplog.at_level(logging.INFO, logger="mediainfo.enrichers.thetvdb"):
        _enricher().enrich(_kingdom_now_playing())

    assert any("could not verify" in r.message for r in caplog.records)


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_logs_when_subtitle_has_no_episode_number_prefix(mock_post, mock_get, caplog):
    import logging

    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.return_value = _response(_AMBIGUOUS_RESULTS)

    with caplog.at_level(logging.INFO, logger="mediainfo.enrichers.thetvdb"):
        _enricher().enrich(_kingdom_now_playing(subtitle="S01E05"))

    assert any("can't disambiguate" in r.message for r in caplog.records)


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_does_not_duplicate_existing_image(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [_response(_ARTWORK_TYPES), _response(_SERIES_ARTWORKS)]

    now_playing = _now_playing()
    now_playing.images.append(Artwork(url="https://thetvdb.com/poster-high.jpg", label="Poster (Kodi)"))

    _enricher().enrich(now_playing)

    urls = [i.url for i in now_playing.images]
    assert urls.count("https://thetvdb.com/poster-high.jpg") == 1
    assert "https://thetvdb.com/background.jpg" in urls


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_relogs_in_on_401(mock_post, mock_get):
    mock_post.side_effect = [
        _response({"data": {"token": "expired-token"}}),
        _response({"data": {"token": "fresh-token"}}),
    ]
    mock_get.side_effect = [
        _response({}, status_code=401),
        _response(_ARTWORK_TYPES),
        _response(_SERIES_ARTWORKS),
    ]

    now_playing = _now_playing()
    _enricher().enrich(now_playing)

    assert len(now_playing.images) == 2
    assert mock_post.call_count == 2


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_login_failure_returns_gracefully(mock_post, mock_get):
    mock_post.side_effect = Exception("boom")

    now_playing = _now_playing()
    _enricher().enrich(now_playing)

    assert now_playing.images == []


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_series_not_found_returns_gracefully(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [_response(_ARTWORK_TYPES), _response({}, status_code=404)]

    now_playing = _now_playing()
    _enricher().enrich(now_playing)

    assert now_playing.images == []


# ---------------------------------------------------------------------------
# original_title fallback (e.g. SVT shows with a Swedish device title)
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_falls_back_to_original_title_when_primary_search_returns_nothing(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [
        _response({"data": []}),          # primary title search → no results
        _response(_SEARCH_RESULTS),       # original_title search → found
        _response(_ARTWORK_TYPES),
        _response(_SERIES_ARTWORKS),
    ]

    now_playing = NowPlaying(
        source="shield", media_type="episode",
        title="Den danska kvinnan", subtitle="5. Brutna ben", ids={},
        original_title="The Danish Woman",
    )
    _enricher().enrich(now_playing)

    assert now_playing.ids["tvdb"] == "98765"
    assert len(now_playing.images) == 2

    # Second search used the original_title.
    second_search = mock_get.call_args_list[1]
    assert second_search.kwargs["params"] == {"query": "The Danish Woman", "type": "series"}


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_does_not_try_original_title_when_primary_search_finds_result(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [
        _response(_SEARCH_RESULTS),   # primary search finds something
        _response(_ARTWORK_TYPES),
        _response(_SERIES_ARTWORKS),
    ]

    now_playing = NowPlaying(
        source="shield", media_type="episode",
        title="Bonusfamiljen", subtitle="1. Avsnitt 1", ids={},
        original_title="The Bonus Family",
    )
    _enricher().enrich(now_playing)

    assert now_playing.ids["tvdb"] == "98765"
    # Only one /search call (the primary one) — original_title not tried.
    search_calls = [c for c in mock_get.call_args_list if "search" in c.args[0]]
    assert len(search_calls) == 1


@patch("mediainfo.enrichers.thetvdb.requests.get")
@patch("mediainfo.enrichers.thetvdb.requests.post")
def test_original_title_fallback_skipped_when_not_set(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.return_value = _response({"data": []})

    now_playing = NowPlaying(
        source="shield", media_type="episode",
        title="Unknown Show", subtitle="1. Episode", ids={},
    )
    _enricher().enrich(now_playing)

    assert now_playing.images == []
    # Only one /search call since original_title is empty.
    assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------

def test_test_connection_success():
    with patch.object(TheTvDbEnricher, "_login", return_value="tok"):
        ok, message = _enricher().test_connection()
    assert ok is True
    assert "Logged in" in message


def test_test_connection_failure():
    with patch.object(TheTvDbEnricher, "_login", return_value=None):
        ok, message = _enricher().test_connection()
    assert ok is False
    assert "Login failed" in message


def test_test_connection_handles_exception():
    with patch.object(TheTvDbEnricher, "_login", side_effect=RuntimeError("boom")):
        ok, message = _enricher().test_connection()
    assert ok is False
    assert "boom" in message
