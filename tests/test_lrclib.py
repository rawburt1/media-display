"""Tests for the LRCLIB lyrics enricher."""

from unittest.mock import MagicMock, patch

from mediainfo.config import LrclibConfig
from mediainfo.enrichers.lrclib import LrclibEnricher
from mediainfo.models import NowPlaying
from mediainfo.stores.text_cache import TextCache


def _config(**kwargs):
    return LrclibConfig(enabled=True, **kwargs)


def _music(artist="Queen", title="Bohemian Rhapsody", album="A Night at the Opera", duration=None):
    return NowPlaying(
        source="kodi",
        media_type="music",
        title=title,
        subtitle=artist,
        album=album,
        duration_seconds=duration,
    )


def _movie(title="Inception"):
    return NowPlaying(source="kodi", media_type="movie", title=title)


def _mock_response(json_data=None, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_skips_non_music_media_types(mock_get):
    enricher = LrclibEnricher(_config())
    np = _movie()

    enricher.enrich(np)

    mock_get.assert_not_called()
    assert np.lyrics == ""


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_skips_when_artist_missing(mock_get):
    enricher = LrclibEnricher(_config())
    np = _music(artist="")

    enricher.enrich(np)

    mock_get.assert_not_called()


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_skips_when_title_missing(mock_get):
    enricher = LrclibEnricher(_config())
    np = _music(title="")

    enricher.enrich(np)

    mock_get.assert_not_called()


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_exact_match_lookup_when_duration_known(mock_get):
    mock_get.return_value = _mock_response(
        {
            "plainLyrics": "Is this the real life",
            "syncedLyrics": "[00:01.00]Is this the real life",
        }
    )
    enricher = LrclibEnricher(_config())
    np = _music(duration=354)

    enricher.enrich(np)

    args, kwargs = mock_get.call_args
    assert args[0] == "https://lrclib.net/api/get"
    assert kwargs["params"]["artist_name"] == "Queen"
    assert kwargs["params"]["track_name"] == "Bohemian Rhapsody"
    assert kwargs["params"]["duration"] == 354
    assert np.lyrics == "Is this the real life"
    assert np.synced_lyrics == "[00:01.00]Is this the real life"


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_falls_back_to_search_when_exact_match_not_found(mock_get):
    mock_get.side_effect = [
        _mock_response(status_code=404),
        _mock_response([{"plainLyrics": "found via search", "syncedLyrics": ""}]),
    ]
    enricher = LrclibEnricher(_config())
    np = _music(duration=354)

    enricher.enrich(np)

    assert mock_get.call_count == 2
    assert mock_get.call_args_list[1].args[0] == "https://lrclib.net/api/search"
    assert np.lyrics == "found via search"


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_uses_search_directly_when_duration_unknown(mock_get):
    mock_get.return_value = _mock_response(
        [{"plainLyrics": "no duration needed", "syncedLyrics": ""}]
    )
    enricher = LrclibEnricher(_config())
    np = _music(duration=None)

    enricher.enrich(np)

    mock_get.assert_called_once()
    assert mock_get.call_args.args[0] == "https://lrclib.net/api/search"
    assert np.lyrics == "no duration needed"


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_search_returns_no_results(mock_get):
    mock_get.return_value = _mock_response([])
    enricher = LrclibEnricher(_config())
    np = _music(duration=None)

    enricher.enrich(np)

    assert np.lyrics == ""
    assert np.synced_lyrics == ""


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_instrumental_track_leaves_lyrics_empty(mock_get):
    mock_get.return_value = _mock_response(
        {
            "instrumental": True,
            "plainLyrics": None,
            "syncedLyrics": None,
        }
    )
    enricher = LrclibEnricher(_config())
    np = _music(duration=200)

    enricher.enrich(np)

    assert np.lyrics == ""
    assert np.synced_lyrics == ""


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_network_exception_does_not_raise(mock_get):
    mock_get.side_effect = RuntimeError("network down")
    enricher = LrclibEnricher(_config())
    np = _music(duration=200)

    enricher.enrich(np)  # must not raise

    assert np.lyrics == ""


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_works_without_a_cache(mock_get):
    mock_get.return_value = _mock_response({"plainLyrics": "no cache needed", "syncedLyrics": ""})
    enricher = LrclibEnricher(_config(), cache=None)
    np = _music(duration=200)

    enricher.enrich(np)  # must not raise

    assert np.lyrics == "no cache needed"


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_caches_result_and_reuses_on_second_lookup(mock_get, tmp_path):
    mock_get.return_value = _mock_response({"plainLyrics": "cached lyrics", "syncedLyrics": ""})
    cache = TextCache(tmp_path)
    enricher = LrclibEnricher(_config(), cache=cache)

    enricher.enrich(_music(duration=200))
    assert mock_get.call_count == 1

    mock_get.reset_mock()
    second_np = _music(duration=200)
    enricher.enrich(second_np)

    mock_get.assert_not_called()
    assert second_np.lyrics == "cached lyrics"


@patch("mediainfo.enrichers.lrclib.requests.get")
def test_different_songs_do_not_share_a_cache_entry(mock_get, tmp_path):
    cache = TextCache(tmp_path)
    enricher = LrclibEnricher(_config(), cache=cache)

    mock_get.return_value = _mock_response({"plainLyrics": "song A lyrics", "syncedLyrics": ""})
    enricher.enrich(_music(title="Song A", duration=200))

    mock_get.return_value = _mock_response({"plainLyrics": "song B lyrics", "syncedLyrics": ""})
    np_b = _music(title="Song B", duration=200)
    enricher.enrich(np_b)

    assert mock_get.call_count == 2
    assert np_b.lyrics == "song B lyrics"
