"""Tests for MediaDataStore - a foundation-only unified artwork/lyrics/
metadata cache, not yet wired into the live app (see the module's own
docstring)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from mediainfo.config import MediaDataConfig, MediaDataRefreshConfig
from mediainfo.media_data_store import MediaDataStore


def _store(tmp_path, refresh=None, **kwargs):
    return MediaDataStore(
        MediaDataConfig(path=str(tmp_path), refresh=refresh or MediaDataRefreshConfig(), **kwargs)
    )


# ---------------------------------------------------------------------------
# Path builders
# ---------------------------------------------------------------------------

def test_movie_dir_includes_year(tmp_path):
    store = _store(tmp_path)
    assert store.movie_dir("Alien", 1979) == tmp_path / "movies" / "Alien (1979)"


def test_series_dir_includes_year(tmp_path):
    store = _store(tmp_path)
    assert store.series_dir("Zero Day", 2025) == tmp_path / "series" / "Zero Day (2025)"


def test_album_dir_includes_artist_and_year(tmp_path):
    store = _store(tmp_path)
    expected = tmp_path / "music" / "Led Zeppelin" / "Houses of the Holy (1973)"
    assert store.album_dir("Led Zeppelin", "Houses of the Holy", 1973) == expected


def test_movie_dir_omits_parens_when_year_missing(tmp_path):
    store = _store(tmp_path)
    assert store.movie_dir("Alien", None) == tmp_path / "movies" / "Alien"


def test_series_dir_omits_parens_when_year_missing(tmp_path):
    store = _store(tmp_path)
    assert store.series_dir("Zero Day", None) == tmp_path / "series" / "Zero Day"


def test_album_dir_omits_parens_when_year_missing(tmp_path):
    store = _store(tmp_path)
    expected = tmp_path / "music" / "Led Zeppelin" / "Houses of the Holy"
    assert store.album_dir("Led Zeppelin", "Houses of the Holy", None) == expected


def test_special_characters_in_title_are_sanitized(tmp_path):
    store = _store(tmp_path)
    path = store.movie_dir("Ocean's 8: A/V Cut", 2018)
    assert "/" not in path.name
    assert ":" not in path.name


def test_special_characters_in_artist_and_album_are_sanitized(tmp_path):
    store = _store(tmp_path)
    path = store.album_dir("AC/DC", "High Voltage", 1976)
    assert "/" not in path.parent.name  # the artist segment
    assert path.parent.name != ""


def test_different_special_character_titles_do_not_collide(tmp_path):
    store = _store(tmp_path)
    a = store.movie_dir("Ke$ha: Behind the Music", 2010)
    b = store.movie_dir("Ke_ha: Behind the Music", 2010)
    assert a != b


def test_movie_dir_is_rooted_under_configured_path(tmp_path):
    store = _store(tmp_path)
    assert store.root == tmp_path.resolve()
    assert str(store.movie_dir("Alien", 1979)).startswith(str(tmp_path.resolve()))


# ---------------------------------------------------------------------------
# Config wiring
# ---------------------------------------------------------------------------

def test_config_from_dict_defaults():
    from mediainfo.config import Config

    config = Config.from_dict({})
    assert config.mediadata.path == "./mediadata"
    assert config.mediadata.cache_first is True
    assert config.mediadata.refresh.enabled is True
    assert config.mediadata.refresh.movies_days == 180
    assert config.mediadata.refresh.series_days == 30
    assert config.mediadata.refresh.music_days == 365


def test_config_from_dict_honors_overrides():
    from mediainfo.config import Config

    config = Config.from_dict({
        "mediadata": {
            "path": "/data/mediadata",
            "cache_first": False,
            "refresh": {"enabled": False, "movies_days": 30, "series_days": 7, "music_days": 90},
        }
    })
    assert config.mediadata.path == "/data/mediadata"
    assert config.mediadata.cache_first is False
    assert config.mediadata.refresh.enabled is False
    assert config.mediadata.refresh.movies_days == 30
    assert config.mediadata.refresh.series_days == 7
    assert config.mediadata.refresh.music_days == 90


def test_config_from_dict_partial_refresh_override_keeps_other_defaults():
    from mediainfo.config import Config

    config = Config.from_dict({"mediadata": {"refresh": {"movies_days": 60}}})
    assert config.mediadata.refresh.movies_days == 60
    assert config.mediadata.refresh.series_days == 30  # untouched default
    assert config.mediadata.refresh.enabled is True


# ---------------------------------------------------------------------------
# metadata.json read/write
# ---------------------------------------------------------------------------

def test_read_metadata_returns_empty_dict_when_missing(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)
    assert store._read_metadata(item_dir) == {}


def test_write_then_read_metadata_round_trips(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)
    data = {"title": "Alien", "year": 1979, "media_type": "movie", "external_ids": {"tmdb": "348"}}

    store._write_metadata(item_dir, data)

    assert store._read_metadata(item_dir) == data


def test_write_metadata_creates_item_directory(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)
    assert not item_dir.exists()

    store._write_metadata(item_dir, {"title": "Alien"})

    assert item_dir.exists()
    assert (item_dir / "metadata.json").exists()


def test_write_metadata_does_not_leave_a_tmp_file_behind(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)

    store._write_metadata(item_dir, {"title": "Alien"})

    assert not (item_dir / "metadata.json.tmp").exists()


def test_read_metadata_returns_empty_dict_for_corrupt_json(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)
    item_dir.mkdir(parents=True)
    (item_dir / "metadata.json").write_text("not valid json{{{", encoding="utf-8")

    assert store._read_metadata(item_dir) == {}


def test_write_metadata_overwrites_previous_content(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)

    store._write_metadata(item_dir, {"title": "Alien", "year": 1979})
    store._write_metadata(item_dir, {"title": "Alien", "year": 1979, "external_ids": {"tmdb": "348"}})

    assert store._read_metadata(item_dir) == {
        "title": "Alien", "year": 1979, "external_ids": {"tmdb": "348"},
    }


# ---------------------------------------------------------------------------
# _resolve_artwork: cache-first + refresh-policy core
# ---------------------------------------------------------------------------

def _seed_stale_entry(store, item_dir, filename, metadata_key, days_old, content=b"old-bytes"):
    """Write an existing artwork file plus a metadata.json entry whose
    last_checked is `days_old` days in the past."""
    path = item_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
    store._write_metadata(item_dir, {
        "artwork": {metadata_key: {
            "path": filename, "source": "tmdb", "last_checked": old_ts, "last_updated": old_ts,
        }},
    })


def test_resolve_artwork_fetches_when_missing(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)
    fetch_fn = MagicMock(return_value=(b"new-bytes", "tmdb"))

    result = store._resolve_artwork(item_dir, "poster.jpg", "poster", 180, fetch_fn)

    fetch_fn.assert_called_once()
    assert result == item_dir / "poster.jpg"
    assert result.read_bytes() == b"new-bytes"
    metadata = store._read_metadata(item_dir)
    entry = metadata["artwork"]["poster"]
    assert entry["source"] == "tmdb"
    assert entry["last_checked"] == entry["last_updated"]


def test_resolve_artwork_returns_none_when_missing_and_fetch_finds_nothing(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)
    fetch_fn = MagicMock(return_value=None)

    result = store._resolve_artwork(item_dir, "poster.jpg", "poster", 180, fetch_fn)

    assert result is None
    assert not (item_dir / "poster.jpg").exists()


def test_resolve_artwork_uses_cache_without_fetching_when_fresh(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)
    _seed_stale_entry(store, item_dir, "poster.jpg", "poster", days_old=1)
    fetch_fn = MagicMock()

    result = store._resolve_artwork(item_dir, "poster.jpg", "poster", 180, fetch_fn)

    fetch_fn.assert_not_called()
    assert result == item_dir / "poster.jpg"
    assert result.read_bytes() == b"old-bytes"


def test_resolve_artwork_refreshes_when_stale(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)
    _seed_stale_entry(store, item_dir, "poster.jpg", "poster", days_old=200)
    fetch_fn = MagicMock(return_value=(b"refreshed-bytes", "tmdb"))

    result = store._resolve_artwork(item_dir, "poster.jpg", "poster", 180, fetch_fn)

    fetch_fn.assert_called_once()
    assert result.read_bytes() == b"refreshed-bytes"
    entry = store._read_metadata(item_dir)["artwork"]["poster"]
    assert entry["last_checked"] == entry["last_updated"]


def test_resolve_artwork_keeps_old_file_when_refresh_fetch_fails(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)
    _seed_stale_entry(store, item_dir, "poster.jpg", "poster", days_old=200)
    fetch_fn = MagicMock(return_value=None)

    result = store._resolve_artwork(item_dir, "poster.jpg", "poster", 180, fetch_fn)

    fetch_fn.assert_called_once()
    assert result.read_bytes() == b"old-bytes"  # unchanged


def test_resolve_artwork_bumps_last_checked_but_not_last_updated_when_fetch_fails(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)
    _seed_stale_entry(store, item_dir, "poster.jpg", "poster", days_old=200)
    old_entry = store._read_metadata(item_dir)["artwork"]["poster"]
    fetch_fn = MagicMock(return_value=None)

    store._resolve_artwork(item_dir, "poster.jpg", "poster", 180, fetch_fn)

    new_entry = store._read_metadata(item_dir)["artwork"]["poster"]
    assert new_entry["last_checked"] != old_entry["last_checked"]
    assert new_entry["last_updated"] == old_entry["last_updated"]


def test_resolve_artwork_bumps_both_timestamps_when_fetch_succeeds(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)
    _seed_stale_entry(store, item_dir, "poster.jpg", "poster", days_old=200)
    old_entry = store._read_metadata(item_dir)["artwork"]["poster"]
    fetch_fn = MagicMock(return_value=(b"new-bytes", "tmdb"))

    store._resolve_artwork(item_dir, "poster.jpg", "poster", 180, fetch_fn)

    new_entry = store._read_metadata(item_dir)["artwork"]["poster"]
    assert new_entry["last_checked"] != old_entry["last_checked"]
    assert new_entry["last_updated"] != old_entry["last_updated"]


def test_resolve_artwork_does_not_refresh_when_refresh_disabled(tmp_path):
    store = _store(tmp_path, refresh=MediaDataRefreshConfig(enabled=False))
    item_dir = store.movie_dir("Alien", 1979)
    _seed_stale_entry(store, item_dir, "poster.jpg", "poster", days_old=200)
    fetch_fn = MagicMock()

    result = store._resolve_artwork(item_dir, "poster.jpg", "poster", 180, fetch_fn)

    fetch_fn.assert_not_called()
    assert result.read_bytes() == b"old-bytes"


def test_resolve_artwork_still_fetches_when_missing_even_if_refresh_disabled(tmp_path):
    store = _store(tmp_path, refresh=MediaDataRefreshConfig(enabled=False))
    item_dir = store.movie_dir("Alien", 1979)
    fetch_fn = MagicMock(return_value=(b"new-bytes", "tmdb"))

    result = store._resolve_artwork(item_dir, "poster.jpg", "poster", 180, fetch_fn)

    fetch_fn.assert_called_once()
    assert result.read_bytes() == b"new-bytes"


def test_resolve_artwork_with_max_age_none_never_refetches_once_present(tmp_path):
    """max_age_days=None is the lyrics case: never stale by age."""
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)
    _seed_stale_entry(store, item_dir, "lyrics.lrc", "lyrics", days_old=10_000)
    fetch_fn = MagicMock()

    result = store._resolve_artwork(item_dir, "lyrics.lrc", "lyrics", None, fetch_fn)

    fetch_fn.assert_not_called()
    assert result.read_bytes() == b"old-bytes"


# ---------------------------------------------------------------------------
# Movies
# ---------------------------------------------------------------------------

def test_get_movie_poster_fetches_when_missing(tmp_path):
    store = _store(tmp_path)
    with patch.object(store, "_fetch_movie_artwork", return_value=(b"poster-bytes", "tmdb")) as fetch:
        result = store.get_movie_poster("Alien", 1979)

    assert result == store.movie_dir("Alien", 1979) / "poster.jpg"
    assert result.read_bytes() == b"poster-bytes"
    fetch.assert_called_once_with("Alien", 1979, "poster")


def test_get_movie_fanart_uses_a_separate_file_from_poster(tmp_path):
    store = _store(tmp_path)
    with patch.object(store, "_fetch_movie_artwork", return_value=(b"fanart-bytes", "tmdb")):
        result = store.get_movie_fanart("Alien", 1979)

    assert result == store.movie_dir("Alien", 1979) / "fanart.jpg"


def test_fetch_movie_artwork_stub_returns_none(tmp_path):
    store = _store(tmp_path)
    assert store._fetch_movie_artwork("Alien", 1979, "poster") is None


def test_refresh_movie_forces_fetch_even_when_fresh(tmp_path):
    store = _store(tmp_path)
    item_dir = store.movie_dir("Alien", 1979)
    _seed_stale_entry(store, item_dir, "poster.jpg", "poster", days_old=1)
    _seed_stale_entry(store, item_dir, "fanart.jpg", "fanart", days_old=1)

    with patch.object(
        store, "_fetch_movie_artwork", return_value=(b"refreshed", "tmdb"),
    ) as fetch:
        updated = store.refresh_movie("Alien", 1979)

    assert fetch.call_count == 2  # poster + fanart, despite both being fresh
    assert updated is True
    assert (item_dir / "poster.jpg").read_bytes() == b"refreshed"


def test_refresh_movie_returns_false_when_stub_finds_nothing(tmp_path):
    store = _store(tmp_path)
    updated = store.refresh_movie("Alien", 1979)  # real stub, always None
    assert updated is False


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------

def test_get_series_poster_fetches_when_missing(tmp_path):
    store = _store(tmp_path)
    with patch.object(store, "_fetch_series_artwork", return_value=(b"poster-bytes", "tvdb")) as fetch:
        result = store.get_series_poster("Zero Day", 2025)

    assert result == store.series_dir("Zero Day", 2025) / "poster.jpg"
    fetch.assert_called_once_with("Zero Day", 2025, "poster")


def test_refresh_series_forces_fetch_even_when_fresh(tmp_path):
    store = _store(tmp_path)
    item_dir = store.series_dir("Zero Day", 2025)
    _seed_stale_entry(store, item_dir, "poster.jpg", "poster", days_old=1)
    _seed_stale_entry(store, item_dir, "fanart.jpg", "fanart", days_old=1)

    with patch.object(store, "_fetch_series_artwork", return_value=(b"refreshed", "tvdb")) as fetch:
        updated = store.refresh_series("Zero Day", 2025)

    assert fetch.call_count == 2
    assert updated is True


def test_series_uses_series_days_refresh_policy_not_movies(tmp_path):
    """Series refreshes more often (30d default) than movies (180d) -
    confirm get_series_poster checks staleness against series_days."""
    store = _store(tmp_path)
    item_dir = store.series_dir("Zero Day", 2025)
    _seed_stale_entry(store, item_dir, "poster.jpg", "poster", days_old=45)  # stale for series, not movies

    with patch.object(store, "_fetch_series_artwork", return_value=(b"new", "tvdb")) as fetch:
        store.get_series_poster("Zero Day", 2025)

    fetch.assert_called_once()  # would NOT have refetched at the movies_days=180 policy


# ---------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------

def test_get_album_art_fetches_when_missing(tmp_path):
    store = _store(tmp_path)
    with patch.object(
        store, "_fetch_album_artwork", return_value=(b"art-bytes", "musicbrainz"),
    ) as fetch:
        result = store.get_album_art("Led Zeppelin", "Houses of the Holy", 1973)

    assert result == store.album_dir("Led Zeppelin", "Houses of the Holy", 1973) / "albumart.jpg"
    fetch.assert_called_once_with("Led Zeppelin", "Houses of the Holy", 1973, "albumart")


def test_refresh_album_forces_fetch_even_when_fresh(tmp_path):
    store = _store(tmp_path)
    item_dir = store.album_dir("Led Zeppelin", "Houses of the Holy", 1973)
    _seed_stale_entry(store, item_dir, "albumart.jpg", "albumart", days_old=1)
    _seed_stale_entry(store, item_dir, "fanart.jpg", "fanart", days_old=1)

    with patch.object(store, "_fetch_album_artwork", return_value=(b"refreshed", "fanarttv")) as fetch:
        updated = store.refresh_album("Led Zeppelin", "Houses of the Holy", 1973)

    assert fetch.call_count == 2
    assert updated is True


def test_album_uses_music_days_refresh_policy(tmp_path):
    store = _store(tmp_path)
    item_dir = store.album_dir("Led Zeppelin", "Houses of the Holy", 1973)
    # Stale for movies (180d)/series (30d) but not for music (365d default).
    _seed_stale_entry(store, item_dir, "albumart.jpg", "albumart", days_old=200)

    with patch.object(store, "_fetch_album_artwork") as fetch:
        store.get_album_art("Led Zeppelin", "Houses of the Holy", 1973)

    fetch.assert_not_called()  # still fresh under the 365-day music policy


# ---------------------------------------------------------------------------
# _relocate_to_year_dir
# ---------------------------------------------------------------------------

def test_relocate_to_year_dir_moves_files(tmp_path):
    store = _store(tmp_path)
    old_dir = store.movie_dir("Alien", None)
    new_dir = store.movie_dir("Alien", 1979)
    old_dir.mkdir(parents=True)
    (old_dir / "poster.jpg").write_bytes(b"poster-bytes")
    store._write_metadata(old_dir, {"title": "Alien", "year": None})

    store._relocate_to_year_dir(old_dir, new_dir)

    assert not old_dir.exists()
    assert (new_dir / "poster.jpg").read_bytes() == b"poster-bytes"
    assert store._read_metadata(new_dir)["year"] is None  # merged as-is; caller updates year


def test_relocate_to_year_dir_merges_into_existing_destination_metadata(tmp_path):
    store = _store(tmp_path)
    old_dir = store.movie_dir("Alien", None)
    new_dir = store.movie_dir("Alien", 1979)
    old_dir.mkdir(parents=True)
    (old_dir / "poster.jpg").write_bytes(b"old-poster")
    store._write_metadata(old_dir, {"artwork": {"poster": {"path": "poster.jpg"}}})
    new_dir.mkdir(parents=True)
    store._write_metadata(new_dir, {"external_ids": {"tmdb": "348"}})

    store._relocate_to_year_dir(old_dir, new_dir)

    merged = store._read_metadata(new_dir)
    assert merged["external_ids"] == {"tmdb": "348"}
    assert merged["artwork"]["poster"]["path"] == "poster.jpg"


def test_relocate_to_year_dir_is_noop_when_old_dir_missing(tmp_path):
    store = _store(tmp_path)
    old_dir = store.movie_dir("Alien", None)
    new_dir = store.movie_dir("Alien", 1979)

    store._relocate_to_year_dir(old_dir, new_dir)  # must not raise

    assert not new_dir.exists()


def test_relocate_to_year_dir_is_noop_when_dirs_are_identical(tmp_path):
    store = _store(tmp_path)
    same_dir = store.movie_dir("Alien", 1979)
    same_dir.mkdir(parents=True)
    (same_dir / "poster.jpg").write_bytes(b"poster-bytes")

    store._relocate_to_year_dir(same_dir, same_dir)  # must not raise or delete anything

    assert (same_dir / "poster.jpg").read_bytes() == b"poster-bytes"


# ---------------------------------------------------------------------------
# Lyrics
# ---------------------------------------------------------------------------

def test_get_track_lyrics_fetches_when_missing(tmp_path):
    store = _store(tmp_path)
    lrc = "[00:01.00]The Song Remains The Same"
    with patch.object(store, "_fetch_lyrics", return_value=(lrc.encode(), "lrclib")) as fetch:
        result = store.get_track_lyrics(
            "Led Zeppelin", "Houses of the Holy", "The Song Remains The Same", year=1973
        )

    fetch.assert_called_once_with("Led Zeppelin", "Houses of the Holy", "The Song Remains The Same")
    assert result == lrc
    lrc_path = (
        store.album_dir("Led Zeppelin", "Houses of the Holy", 1973)
        / "The Song Remains The Same.lrc"
    )
    assert lrc_path.read_text(encoding="utf-8") == lrc


def test_get_track_lyrics_returns_none_when_fetch_finds_nothing(tmp_path):
    store = _store(tmp_path)
    result = store.get_track_lyrics("Led Zeppelin", "Houses of the Holy", "The Rain Song")
    assert result is None  # real stub, always None


def test_get_track_lyrics_records_tracks_entry_in_album_metadata(tmp_path):
    store = _store(tmp_path)
    with patch.object(store, "_fetch_lyrics", return_value=(b"lyrics", "lrclib")):
        store.get_track_lyrics("Led Zeppelin", "Houses of the Holy", "The Ocean", year=1973)

    metadata = store._read_metadata(store.album_dir("Led Zeppelin", "Houses of the Holy", 1973))
    entry = metadata["tracks"]["The Ocean"]["lyrics"]
    assert entry["path"] == "The Ocean.lrc"
    assert entry["source"] == "lrclib"
    assert entry["last_checked"] == entry["last_updated"]


def test_lyrics_never_auto_refreshed_by_age(tmp_path):
    store = _store(tmp_path)
    item_dir = store.album_dir("Led Zeppelin", "Houses of the Holy", None)
    item_dir.mkdir(parents=True)
    (item_dir / "Dancing Days.lrc").write_text("[00:01.00]old lyrics", encoding="utf-8")
    ancient = (datetime.now(timezone.utc) - timedelta(days=10_000)).isoformat()
    store._write_metadata(item_dir, {
        "tracks": {"Dancing Days": {"lyrics": {
            "path": "Dancing Days.lrc", "source": "lrclib",
            "last_checked": ancient, "last_updated": ancient,
        }}},
    })

    with patch.object(store, "_fetch_lyrics") as fetch:
        result = store.get_track_lyrics("Led Zeppelin", "Houses of the Holy", "Dancing Days")

    fetch.assert_not_called()
    assert result == "[00:01.00]old lyrics"


def test_refresh_track_lyrics_forces_fetch_even_when_cached(tmp_path):
    store = _store(tmp_path)
    with patch.object(store, "_fetch_lyrics", return_value=(b"first version", "lrclib")):
        store.get_track_lyrics("Led Zeppelin", "Houses of the Holy", "No Quarter", year=1973)

    with patch.object(store, "_fetch_lyrics", return_value=(b"corrected version", "lrclib")) as fetch:
        updated = store.refresh_track_lyrics(
            "Led Zeppelin", "Houses of the Holy", "No Quarter", year=1973
        )

    fetch.assert_called_once()
    assert updated is True
    assert store.get_track_lyrics(
        "Led Zeppelin", "Houses of the Holy", "No Quarter", year=1973
    ) == "corrected version"


def test_refresh_track_lyrics_keeps_old_file_when_fetch_fails(tmp_path):
    store = _store(tmp_path)
    with patch.object(store, "_fetch_lyrics", return_value=(b"good lyrics", "lrclib")):
        store.get_track_lyrics("Led Zeppelin", "Houses of the Holy", "The Crunge", year=1973)

    updated = store.refresh_track_lyrics(
        "Led Zeppelin", "Houses of the Holy", "The Crunge", year=1973
    )  # real stub: fetch returns None

    assert updated is False
    assert store.get_track_lyrics(
        "Led Zeppelin", "Houses of the Holy", "The Crunge", year=1973
    ) == "good lyrics"


def test_track_title_with_special_characters_gets_safe_lrc_filename(tmp_path):
    store = _store(tmp_path)
    with patch.object(store, "_fetch_lyrics", return_value=(b"lyrics", "lrclib")):
        result = store.get_track_lyrics("Prince", "Parade", 'Girls & Boys: "Live"/Mix', year=1986)

    assert result == "lyrics"
    item_dir = store.album_dir("Prince", "Parade", 1986)
    lrc_files = list(item_dir.glob("*.lrc"))
    assert len(lrc_files) == 1
    assert "/" not in lrc_files[0].name
    assert '"' not in lrc_files[0].name


def test_lyrics_and_artwork_share_the_same_album_metadata_file(tmp_path):
    store = _store(tmp_path)
    with patch.object(store, "_fetch_album_artwork", return_value=(b"art", "musicbrainz")):
        store.get_album_art("Led Zeppelin", "Houses of the Holy", 1973)
    with patch.object(store, "_fetch_lyrics", return_value=(b"lyrics", "lrclib")):
        store.get_track_lyrics("Led Zeppelin", "Houses of the Holy", "The Ocean", year=1973)

    metadata = store._read_metadata(store.album_dir("Led Zeppelin", "Houses of the Holy", 1973))
    assert "albumart" in metadata["artwork"]
    assert "The Ocean" in metadata["tracks"]
