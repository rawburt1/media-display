"""Tests for the local MusicLibrary metadata cache."""

import time

from mediainfo.musiclibrary import MusicLibrary


def _library(tmp_path, max_age_days=30):
    return MusicLibrary(str(tmp_path / "library.db"), max_age_days=max_age_days)


# ---------------------------------------------------------------------------
# Canonical entities
# ---------------------------------------------------------------------------

def test_get_or_create_artist_is_idempotent(tmp_path):
    lib = _library(tmp_path)
    first = lib.get_or_create_artist("Pink Floyd")
    second = lib.get_or_create_artist("Pink Floyd")
    assert first == second


def test_different_artists_get_different_ids(tmp_path):
    lib = _library(tmp_path)
    a = lib.get_or_create_artist("Pink Floyd")
    b = lib.get_or_create_artist("Queen")
    assert a != b


def test_get_or_create_album_is_idempotent_per_artist(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    first = lib.get_or_create_album(artist_id, "The Wall")
    second = lib.get_or_create_album(artist_id, "The Wall")
    assert first == second


def test_same_album_title_under_different_artists_is_distinct(tmp_path):
    lib = _library(tmp_path)
    artist_a = lib.get_or_create_artist("Artist A")
    artist_b = lib.get_or_create_artist("Artist B")
    album_a = lib.get_or_create_album(artist_a, "Greatest Hits")
    album_b = lib.get_or_create_album(artist_b, "Greatest Hits")
    assert album_a != album_b


def test_get_or_create_track_is_idempotent_per_artist(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Phil Collins")
    first = lib.get_or_create_track(artist_id, "In the Air Tonight")
    second = lib.get_or_create_track(artist_id, "In the Air Tonight")
    assert first == second


# ---------------------------------------------------------------------------
# MusicBrainz ids
# ---------------------------------------------------------------------------

def test_mbid_defaults_to_none(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    assert lib.get_mbid("artist", artist_id) is None


def test_set_and_get_mbid(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    lib.set_mbid("artist", artist_id, "83d91898-7763-47d7-b03b-b92132375c47")
    assert lib.get_mbid("artist", artist_id) == "83d91898-7763-47d7-b03b-b92132375c47"


def test_mbid_persists_across_library_instances(tmp_path):
    db_path = tmp_path / "library.db"
    lib1 = MusicLibrary(str(db_path))
    artist_id = lib1.get_or_create_artist("Pink Floyd")
    lib1.set_mbid("artist", artist_id, "known-mbid")
    lib1.close()

    lib2 = MusicLibrary(str(db_path))
    assert lib2.get_mbid("artist", artist_id) == "known-mbid"


# ---------------------------------------------------------------------------
# find_artist / find_track (lookup without create)
# ---------------------------------------------------------------------------

def test_find_artist_returns_none_when_missing(tmp_path):
    lib = _library(tmp_path)
    assert lib.find_artist("Pink Floyd") is None


def test_find_artist_returns_existing_id(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    assert lib.find_artist("Pink Floyd") == artist_id


def test_find_track_returns_none_when_missing(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    assert lib.find_track(artist_id, "Comfortably Numb") is None


def test_find_track_returns_existing_id(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    track_id = lib.get_or_create_track(artist_id, "Comfortably Numb")
    assert lib.find_track(artist_id, "Comfortably Numb") == track_id


# ---------------------------------------------------------------------------
# track <-> album linkage
# ---------------------------------------------------------------------------

def test_get_albums_for_track_returns_empty_when_unlinked(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    track_id = lib.get_or_create_track(artist_id, "Comfortably Numb")
    assert lib.get_albums_for_track(track_id) == []


def test_link_track_album_and_retrieve(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    track_id = lib.get_or_create_track(artist_id, "Comfortably Numb")
    album_id = lib.get_or_create_album(artist_id, "The Wall")
    lib.set_mbid("album", album_id, "wall-mbid")

    lib.link_track_album(track_id, album_id)

    albums = lib.get_albums_for_track(track_id)
    assert albums == [(album_id, "The Wall", "wall-mbid")]


def test_link_track_to_multiple_albums(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    track_id = lib.get_or_create_track(artist_id, "Comfortably Numb")
    wall_id = lib.get_or_create_album(artist_id, "The Wall")
    live_id = lib.get_or_create_album(artist_id, "Is There Anybody Out There?")

    lib.link_track_album(track_id, wall_id)
    lib.link_track_album(track_id, live_id)

    albums = lib.get_albums_for_track(track_id)
    assert {title for _, title, _ in albums} == {"The Wall", "Is There Anybody Out There?"}


def test_link_track_album_is_idempotent(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    track_id = lib.get_or_create_track(artist_id, "Comfortably Numb")
    album_id = lib.get_or_create_album(artist_id, "The Wall")

    lib.link_track_album(track_id, album_id)
    lib.link_track_album(track_id, album_id)  # should not raise or duplicate

    assert len(lib.get_albums_for_track(track_id)) == 1


# ---------------------------------------------------------------------------
# Source claims
# ---------------------------------------------------------------------------

def test_claim_defaults_to_none(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    assert lib.get_claim("artist", artist_id, "photo_url", "lastfm") is None


def test_set_and_get_claim(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    lib.set_claim("artist", artist_id, "photo_url", "lastfm", "https://example.com/pf.jpg")
    assert lib.get_claim("artist", artist_id, "photo_url", "lastfm") == "https://example.com/pf.jpg"


def test_empty_string_claim_is_a_valid_cached_negative_result(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    lib.set_claim("artist", artist_id, "photo_url", "lastfm", "")
    assert lib.get_claim("artist", artist_id, "photo_url", "lastfm") == ""


def test_claims_from_different_sources_are_independent(tmp_path):
    lib = _library(tmp_path)
    album_id = lib.get_or_create_album(lib.get_or_create_artist("Pink Floyd"), "The Wall")
    lib.set_claim("album", album_id, "cover_art_url", "discogs", "https://discogs/cover.jpg")
    lib.set_claim("album", album_id, "cover_art_url", "musicbrainz", "https://caa/cover.jpg")
    assert lib.get_claim("album", album_id, "cover_art_url", "discogs") == "https://discogs/cover.jpg"
    assert lib.get_claim("album", album_id, "cover_art_url", "musicbrainz") == "https://caa/cover.jpg"


def test_set_claim_overwrites_previous_value(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    lib.set_claim("artist", artist_id, "photo_url", "lastfm", "https://old.jpg")
    lib.set_claim("artist", artist_id, "photo_url", "lastfm", "https://new.jpg")
    assert lib.get_claim("artist", artist_id, "photo_url", "lastfm") == "https://new.jpg"


def test_stale_claim_returns_none(tmp_path):
    lib = _library(tmp_path, max_age_days=0)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    lib.set_claim("artist", artist_id, "photo_url", "lastfm", "https://example.com/pf.jpg")
    time.sleep(0.01)
    assert lib.get_claim("artist", artist_id, "photo_url", "lastfm") is None
