"""Tests for the lrclib.net synced-lyrics enricher."""

from unittest.mock import MagicMock, patch

from mediainfo.config import LrclibConfig
from mediainfo.enrichers.lrclib import LrclibEnricher
from mediainfo.models import NowPlaying
from mediainfo.musiclibrary import MusicLibrary


def _enricher() -> LrclibEnricher:
    return LrclibEnricher(LrclibConfig(enabled=True))


def _music(title="Comfortably Numb", artist="Pink Floyd"):
    return NowPlaying(source="kodi", media_type="music", title=title, subtitle=artist)


def _response(status_code=200, json_data=None):
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    response.json.return_value = json_data if json_data is not None else []
    return response


_SYNCED = "[00:01.50]Hello\n[00:05.00]Is there anybody in there?"


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_non_music_is_skipped(mock_get):
    np = NowPlaying(source="kodi", media_type="movie", title="The Matrix")
    _enricher().enrich(np)
    mock_get.assert_not_called()
    assert np.lyrics_synced == ""


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_sets_synced_lyrics_on_success(mock_get):
    mock_get.return_value = _response(json_data=[{"syncedLyrics": _SYNCED}])

    np = _music()
    _enricher().enrich(np)

    assert np.lyrics_synced == _SYNCED


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_uses_artist_and_title_as_query_params(mock_get):
    mock_get.return_value = _response(json_data=[{"syncedLyrics": _SYNCED}])

    _enricher().enrich(_music(title="Money", artist="Pink Floyd"))

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["track_name"] == "Money"
    assert kwargs["params"]["artist_name"] == "Pink Floyd"


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_skips_results_with_no_synced_lyrics(mock_get):
    mock_get.return_value = _response(
        json_data=[{"syncedLyrics": "", "plainLyrics": "..."}, {"syncedLyrics": _SYNCED}]
    )

    np = _music()
    _enricher().enrich(np)

    assert np.lyrics_synced == _SYNCED


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_no_results_leaves_lyrics_synced_empty(mock_get):
    mock_get.return_value = _response(json_data=[])

    np = _music()
    _enricher().enrich(np)

    assert np.lyrics_synced == ""


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_caches_lookup_by_artist_and_title(mock_get):
    mock_get.return_value = _response(json_data=[{"syncedLyrics": _SYNCED}])

    enricher = _enricher()
    enricher.enrich(_music())
    enricher.enrich(_music())

    mock_get.assert_called_once()


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_network_error_leaves_lyrics_synced_empty(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")

    np = _music()
    _enricher().enrich(np)

    assert np.lyrics_synced == ""


def test_missing_artist_or_title_is_skipped():
    enricher = _enricher()
    np = NowPlaying(source="kodi", media_type="music", title="Money", subtitle="")
    enricher.enrich(np)
    assert np.lyrics_synced == ""


# ---------------------------------------------------------------------------
# MusicLibrary persistence (forever, never re-fetched)
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.lrclib.requests.get")
def test_caches_result_in_library_and_skips_lookup_on_repeat(mock_get, tmp_path):
    library = MusicLibrary(str(tmp_path / "library.db"))
    mock_get.return_value = _response(json_data=[{"syncedLyrics": _SYNCED}])
    enricher = LrclibEnricher(LrclibConfig(enabled=True), library)

    enricher.enrich(_music())
    assert mock_get.call_count == 1

    np2 = _music()
    enricher.enrich(np2)
    assert mock_get.call_count == 1  # no new network call
    assert np2.lyrics_synced == _SYNCED


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_caches_negative_result_in_library(mock_get, tmp_path):
    library = MusicLibrary(str(tmp_path / "library.db"))
    mock_get.return_value = _response(json_data=[])
    enricher = LrclibEnricher(LrclibConfig(enabled=True), library)

    enricher.enrich(_music())
    assert mock_get.call_count == 1

    enricher.enrich(_music())
    assert mock_get.call_count == 1  # cached miss, no new call
