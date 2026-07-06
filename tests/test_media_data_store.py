"""Tests for MediaDataStore - a foundation-only unified artwork/lyrics/
metadata cache, not yet wired into the live app (see the module's own
docstring)."""

from mediainfo.config import MediaDataConfig
from mediainfo.media_data_store import MediaDataStore


def _store(tmp_path, **kwargs):
    return MediaDataStore(MediaDataConfig(path=str(tmp_path), **kwargs))


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
