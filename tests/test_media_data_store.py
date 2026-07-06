"""Tests for MediaDataStore - a foundation-only unified artwork/lyrics/
metadata cache, not yet wired into the live app (see the module's own
docstring)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

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
