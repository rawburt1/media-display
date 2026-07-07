"""Tests for the shared NowPlaying/Artwork data model."""

from typing import Any
from mediainfo.models import Artwork, NowPlaying


def _now_playing(**kwargs) -> NowPlaying:
    defaults: dict[str, Any] = dict(source="kodi", media_type="movie", title="Movie", subtitle="")
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def test_identity_is_source_title_subtitle():
    np = _now_playing(source="plex", title="The Matrix", subtitle="1999")
    assert np.identity == ("plex", "The Matrix", "1999")


def test_identity_ignores_images():
    a = _now_playing(images=[Artwork(url="https://a/1.jpg")])
    b = _now_playing(images=[Artwork(url="https://b/2.jpg")])
    assert a.identity == b.identity


def test_identity_differs_on_title_change():
    a = _now_playing(title="Movie A")
    b = _now_playing(title="Movie B")
    assert a.identity != b.identity


def test_identity_differs_on_source_change():
    a = _now_playing(source="kodi")
    b = _now_playing(source="plex")
    assert a.identity != b.identity


def test_identity_differs_on_subtitle_change():
    a = _now_playing(subtitle="S01E01")
    b = _now_playing(subtitle="S01E02")
    assert a.identity != b.identity


def test_defaults_are_empty():
    np = NowPlaying(source="kodi", media_type="movie", title="Movie")
    assert np.subtitle == ""
    assert np.album == ""
    assert np.images == []
    assert np.ids == {}
    assert np.season is None
    assert np.year is None
    assert np.summary == ""
    assert np.discography == []
    assert np.rating is None
    assert np.lyrics == ""
    assert np.synced_lyrics == ""
    assert np.ai_text == {}


def test_lyrics_and_ai_text_fields_are_independent_per_instance():
    # default_factory={} guards against the classic mutable-default bug -
    # confirm two instances don't share the same dict.
    a = _now_playing()
    b = _now_playing()
    a.ai_text["mood"] = "melancholy"
    assert b.ai_text == {}


def test_artwork_defaults():
    art = Artwork(url="https://example.com/a.jpg")
    assert art.auth is None
    assert art.label == ""
