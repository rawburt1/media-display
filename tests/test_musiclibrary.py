"""Tests for the local MusicLibrary metadata cache."""

import sqlite3
import time
from unittest.mock import MagicMock

from mediainfo.stores.musiclibrary import MusicLibrary, normalize


def _library(tmp_path, max_age_days=30):
    return MusicLibrary(str(tmp_path / "library.db"), max_age_days=max_age_days)


# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------


def test_normalize_lowercases():
    assert normalize("Pink Floyd") == "pink floyd"


def test_normalize_folds_ampersand_to_and():
    assert normalize("Simon & Garfunkel") == normalize("Simon and Garfunkel")


def test_normalize_strips_accents():
    assert normalize("Beyoncé") == "beyonce"


def test_normalize_strips_punctuation():
    assert normalize("Guns N' Roses") == normalize("Guns N Roses")


def test_normalize_collapses_whitespace():
    assert normalize("The   Beatles") == normalize("The Beatles")


def test_normalize_ignores_leading_trailing_whitespace():
    assert normalize("  Queen  ") == "queen"


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
# Fuzzy matching
# ---------------------------------------------------------------------------


def test_get_or_create_artist_matches_different_case(tmp_path):
    lib = _library(tmp_path)
    first = lib.get_or_create_artist("Pink Floyd")
    second = lib.get_or_create_artist("pink floyd")
    assert first == second


def test_get_or_create_artist_matches_ampersand_variant(tmp_path):
    lib = _library(tmp_path)
    first = lib.get_or_create_artist("Simon & Garfunkel")
    second = lib.get_or_create_artist("Simon and Garfunkel")
    assert first == second


def test_get_or_create_artist_matches_accent_variant(tmp_path):
    lib = _library(tmp_path)
    first = lib.get_or_create_artist("Beyoncé")
    second = lib.get_or_create_artist("Beyonce")
    assert first == second


def test_get_or_create_artist_keeps_original_text_from_first_insert(tmp_path):
    lib = _library(tmp_path)
    lib.get_or_create_artist("Pink Floyd")
    lib.get_or_create_artist("PINK FLOYD")  # matches, doesn't overwrite
    row = lib._conn.execute("SELECT name FROM artists").fetchone()
    assert row[0] == "Pink Floyd"


def test_get_or_create_track_matches_punctuation_variant(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Guns N' Roses")
    first = lib.get_or_create_track(artist_id, "Don't Cry")
    second = lib.get_or_create_track(artist_id, "Dont Cry")
    assert first == second


def test_find_artist_matches_different_case(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    assert lib.find_artist("pink floyd") == artist_id


def test_find_track_matches_ampersand_variant(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    track_id = lib.get_or_create_track(artist_id, "Mother & Father")
    assert lib.find_track(artist_id, "Mother and Father") == track_id


def test_normalized_column_migration_backfills_legacy_database(tmp_path):
    db_path = tmp_path / "legacy.db"
    # Simulate a database created before fuzzy matching existed: same
    # tables, but no *_normalized columns.
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE artists (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, mbid TEXT, updated_at REAL NOT NULL
        );
        INSERT INTO artists (id, name, updated_at) VALUES (1, 'Pink Floyd', 0);
    """)
    conn.commit()
    conn.close()

    lib = MusicLibrary(str(db_path))
    assert lib.find_artist("pink floyd") == 1


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
# random_albums / search / albums_for_artist / tracks_for_artist / stats
# ---------------------------------------------------------------------------


def test_random_albums_only_returns_albums_with_mbid(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    with_mbid = lib.get_or_create_album(artist_id, "The Wall")
    lib.set_mbid("album", with_mbid, "wall-mbid")
    lib.get_or_create_album(artist_id, "Unreleased Demos")  # no mbid

    albums = lib.random_albums(10)
    assert len(albums) == 1
    assert albums[0] == (with_mbid, "Pink Floyd", "The Wall", "wall-mbid")


def test_random_albums_respects_limit(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    for i in range(5):
        album_id = lib.get_or_create_album(artist_id, f"Album {i}")
        lib.set_mbid("album", album_id, f"mbid-{i}")

    assert len(lib.random_albums(3)) == 3
    assert len(lib.random_albums(100)) == 5


def test_search_matches_substring_case_insensitive(tmp_path):
    lib = _library(tmp_path)
    lib.get_or_create_artist("Pink Floyd")
    lib.get_or_create_artist("Queen")

    results = lib.search("pink")
    assert [name for _, name in results] == ["Pink Floyd"]


def test_search_matches_normalized_form(tmp_path):
    lib = _library(tmp_path)
    lib.get_or_create_artist("Simon & Garfunkel")

    results = lib.search("simon and garfunkel")
    assert [name for _, name in results] == ["Simon & Garfunkel"]


def test_search_returns_empty_for_no_match(tmp_path):
    lib = _library(tmp_path)
    lib.get_or_create_artist("Pink Floyd")
    assert lib.search("nonexistent") == []


def test_albums_for_artist_returns_sorted_titles(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    lib.get_or_create_album(artist_id, "The Wall")
    lib.get_or_create_album(artist_id, "Animals")

    albums = lib.albums_for_artist(artist_id)
    assert [title for _, title, _ in albums] == ["Animals", "The Wall"]


def test_tracks_for_artist_returns_sorted_titles(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    lib.get_or_create_track(artist_id, "Money")
    lib.get_or_create_track(artist_id, "Breathe")

    tracks = lib.tracks_for_artist(artist_id)
    assert [title for _, title, _ in tracks] == ["Breathe", "Money"]


def test_stats_counts_entities(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    lib.get_or_create_album(artist_id, "The Wall")
    lib.get_or_create_track(artist_id, "Money")
    lib.get_or_create_track(artist_id, "Breathe")

    assert lib.stats() == {"artists": 1, "albums": 1, "tracks": 2}


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
    assert (
        lib.get_claim("album", album_id, "cover_art_url", "discogs") == "https://discogs/cover.jpg"
    )
    assert (
        lib.get_claim("album", album_id, "cover_art_url", "musicbrainz") == "https://caa/cover.jpg"
    )


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


def test_get_claim_max_age_override_widens_the_default(tmp_path):
    lib = _library(tmp_path, max_age_days=0)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    lib.set_claim("artist", artist_id, "photo_url", "lastfm", "https://example.com/pf.jpg")
    time.sleep(0.01)

    assert lib.get_claim("artist", artist_id, "photo_url", "lastfm") is None
    assert (
        lib.get_claim("artist", artist_id, "photo_url", "lastfm", max_age_seconds=float("inf"))
        == "https://example.com/pf.jpg"
    )


def test_get_claim_max_age_override_narrows_the_default(tmp_path):
    lib = _library(tmp_path, max_age_days=30)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    lib.set_claim("artist", artist_id, "photo_url", "lastfm", "https://example.com/pf.jpg")
    time.sleep(0.01)

    assert lib.get_claim("artist", artist_id, "photo_url", "lastfm") == "https://example.com/pf.jpg"
    assert lib.get_claim("artist", artist_id, "photo_url", "lastfm", max_age_seconds=0) is None


# ---------------------------------------------------------------------------
# get_or_fetch
# ---------------------------------------------------------------------------


def test_get_or_fetch_calls_fetch_fn_on_cache_miss(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    fetch_fn = MagicMock(return_value="https://example.com/pf.jpg")

    result = lib.get_or_fetch("artist", artist_id, "photo_url", "lastfm", fetch_fn)

    assert result == "https://example.com/pf.jpg"
    fetch_fn.assert_called_once()


def test_get_or_fetch_caches_the_fetched_value(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    fetch_fn = MagicMock(return_value="https://example.com/pf.jpg")

    lib.get_or_fetch("artist", artist_id, "photo_url", "lastfm", fetch_fn)
    result = lib.get_or_fetch("artist", artist_id, "photo_url", "lastfm", fetch_fn)

    assert result == "https://example.com/pf.jpg"
    fetch_fn.assert_called_once()  # second call was a cache hit


def test_get_or_fetch_caches_a_negative_result(tmp_path):
    lib = _library(tmp_path)
    artist_id = lib.get_or_create_artist("Pink Floyd")
    fetch_fn = MagicMock(return_value=None)

    first = lib.get_or_fetch("artist", artist_id, "photo_url", "lastfm", fetch_fn)
    second = lib.get_or_fetch("artist", artist_id, "photo_url", "lastfm", fetch_fn)

    assert first is None
    assert second is None
    fetch_fn.assert_called_once()  # second call was a cached miss, not a re-fetch


def test_get_or_fetch_respects_max_age_seconds_override(tmp_path):
    lib = _library(tmp_path, max_age_days=0)
    track_id = lib.get_or_create_track(lib.get_or_create_artist("Pink Floyd"), "Money")
    fetch_fn = MagicMock(return_value="bio text")

    lib.get_or_fetch("track", track_id, "bio", "wikipedia", fetch_fn, max_age_seconds=float("inf"))
    time.sleep(0.01)
    result = lib.get_or_fetch(
        "track", track_id, "bio", "wikipedia", fetch_fn, max_age_seconds=float("inf")
    )

    assert result == "bio text"
    fetch_fn.assert_called_once()  # not re-fetched despite max_age_days=0 on the library
