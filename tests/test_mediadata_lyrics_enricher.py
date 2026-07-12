"""Tests for the MediaDataStore-backed lyrics enricher."""

from unittest.mock import Mock

from mediainfo.enrichers.mediadata_lyrics import MediaDataLyricsEnricher
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import NowPlaying


def _song(**kwargs):
    defaults = dict(
        source="youtube",
        media_type="music",
        title="Comfortably Numb",
        subtitle="Pink Floyd",
        album="The Wall",
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def test_sets_lyrics_on_hit():
    store = Mock(spec=MediaDataStore)
    store.get_track_lyrics.return_value = "[00:01.00] Hello, is there anybody in there?"

    np = _song()
    MediaDataLyricsEnricher(config=object(), store=store).enrich(np)

    store.get_track_lyrics.assert_called_once_with(
        "Pink Floyd", "The Wall", "Comfortably Numb", None
    )
    assert np.lyrics == "[00:01.00] Hello, is there anybody in there?"


def test_no_op_on_store_miss():
    store = Mock(spec=MediaDataStore)
    store.get_track_lyrics.return_value = None

    np = _song()
    MediaDataLyricsEnricher(config=object(), store=store).enrich(np)

    assert np.lyrics == ""


def test_no_op_when_store_is_none():
    np = _song()
    MediaDataLyricsEnricher(config=object(), store=None).enrich(np)
    assert np.lyrics == ""


def test_no_op_for_non_music():
    store = Mock(spec=MediaDataStore)
    np = _song(media_type="movie")
    MediaDataLyricsEnricher(config=object(), store=store).enrich(np)
    assert np.lyrics == ""
    store.get_track_lyrics.assert_not_called()


def test_no_op_without_artist_or_title():
    store = Mock(spec=MediaDataStore)
    np = _song(subtitle="", title="")
    MediaDataLyricsEnricher(config=object(), store=store).enrich(np)
    store.get_track_lyrics.assert_not_called()


def test_swallows_store_exception():
    store = Mock(spec=MediaDataStore)
    store.get_track_lyrics.side_effect = RuntimeError("disk error")

    np = _song()
    MediaDataLyricsEnricher(config=object(), store=store).enrich(np)

    assert np.lyrics == ""
