"""Tests for the lyrics.ovh lyrics enricher."""

from unittest.mock import MagicMock, patch

from mediainfo.config import LyricsConfig
from mediainfo.enrichers.lyrics import LyricsEnricher
from mediainfo.models import NowPlaying
from mediainfo.musiclibrary import MusicLibrary


def _enricher() -> LyricsEnricher:
    return LyricsEnricher(LyricsConfig(enabled=True))


def _music(title="Comfortably Numb", artist="Pink Floyd"):
    return NowPlaying(source="kodi", media_type="music", title=title, subtitle=artist)


def _response(status_code=200, json_data=None):
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    response.json.return_value = json_data or {}
    return response


@patch("mediainfo.enrichers.lyrics.requests.get")
def test_non_music_is_skipped(mock_get):
    np = NowPlaying(source="kodi", media_type="movie", title="The Matrix")
    _enricher().enrich(np)
    mock_get.assert_not_called()
    assert np.lyrics == ""


@patch("mediainfo.enrichers.lyrics.requests.get")
def test_sets_lyrics_on_success(mock_get):
    mock_get.return_value = _response(json_data={"lyrics": "Hello\nIs there anybody in there?"})

    np = _music()
    _enricher().enrich(np)

    assert np.lyrics == "Hello\nIs there anybody in there?"


@patch("mediainfo.enrichers.lyrics.requests.get")
def test_uses_artist_and_title_in_url(mock_get):
    mock_get.return_value = _response(json_data={"lyrics": "..."})

    _enricher().enrich(_music(title="Money", artist="Pink Floyd"))

    url = mock_get.call_args[0][0]
    assert "Pink%20Floyd" in url
    assert "Money" in url


@patch("mediainfo.enrichers.lyrics.requests.get")
def test_404_leaves_lyrics_empty(mock_get):
    mock_get.return_value = _response(status_code=404)

    np = _music()
    _enricher().enrich(np)

    assert np.lyrics == ""


@patch("mediainfo.enrichers.lyrics.requests.get")
def test_caches_lookup_by_artist_and_title(mock_get):
    mock_get.return_value = _response(json_data={"lyrics": "La la la"})

    enricher = _enricher()
    enricher.enrich(_music())
    enricher.enrich(_music())

    mock_get.assert_called_once()


@patch("mediainfo.enrichers.lyrics.requests.get")
def test_network_error_leaves_lyrics_empty(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")

    np = _music()
    _enricher().enrich(np)

    assert np.lyrics == ""


def test_missing_artist_or_title_is_skipped():
    enricher = _enricher()
    np = NowPlaying(source="kodi", media_type="music", title="Money", subtitle="")
    enricher.enrich(np)
    assert np.lyrics == ""


# ---------------------------------------------------------------------------
# MusicLibrary persistence (forever, never re-fetched)
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.lyrics.requests.get")
def test_caches_result_in_library_and_skips_lookup_on_repeat(mock_get, tmp_path):
    library = MusicLibrary(str(tmp_path / "library.db"))
    mock_get.return_value = _response(json_data={"lyrics": "Is this the real life?"})
    enricher = LyricsEnricher(LyricsConfig(enabled=True), library)

    enricher.enrich(_music())
    assert mock_get.call_count == 1

    np2 = _music()
    enricher.enrich(np2)
    assert mock_get.call_count == 1  # no new network call
    assert np2.lyrics == "Is this the real life?"


@patch("mediainfo.enrichers.lyrics.requests.get")
def test_caches_negative_result_in_library(mock_get, tmp_path):
    library = MusicLibrary(str(tmp_path / "library.db"))
    mock_get.return_value = _response(status_code=404)
    enricher = LyricsEnricher(LyricsConfig(enabled=True), library)

    enricher.enrich(_music())
    assert mock_get.call_count == 1

    enricher.enrich(_music())
    assert mock_get.call_count == 1  # cached miss, no new call


@patch("mediainfo.enrichers.lyrics.requests.get")
def test_library_cached_lyrics_never_expire(mock_get, tmp_path):
    library = MusicLibrary(str(tmp_path / "library.db"), max_age_days=0)
    mock_get.return_value = _response(json_data={"lyrics": "Hello"})
    enricher = LyricsEnricher(LyricsConfig(enabled=True), library)

    enricher.enrich(_music())
    # max_age_days=0 would make every other claim type stale immediately -
    # lyrics must still be served from cache regardless.
    enricher.enrich(_music())

    assert mock_get.call_count == 1
