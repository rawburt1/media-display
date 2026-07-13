"""Tests for the local music library idle wallpaper source."""

from unittest.mock import patch

from mediainfo.config import LibraryIdleConfig
from mediainfo.idle.library import LibraryWallpaperSource
from mediainfo.stores.musiclibrary import MusicLibrary


def _library(tmp_path):
    return MusicLibrary(str(tmp_path / "library.db"))


def _seed_album(library, artist="Pink Floyd", title="The Wall", mbid="wall-mbid"):
    artist_id = library.get_or_create_artist(artist)
    album_id = library.get_or_create_album(artist_id, title)
    library.set_mbid("album", album_id, mbid)
    return album_id


def _source(library, **kwargs):
    defaults = dict(enabled=True, batch_size=10, rotation_interval_seconds=300)
    defaults.update(kwargs)
    return LibraryWallpaperSource(LibraryIdleConfig(**defaults), library)


@patch("mediainfo.idle.library.fetch_front_cover")
def test_returns_wallpapers_for_random_albums(mock_fetch, tmp_path):
    library = _library(tmp_path)
    _seed_album(library)
    mock_fetch.return_value = "https://caa.example.com/wall.jpg"

    artworks = _source(library).get_wallpapers()

    assert len(artworks) == 1
    assert artworks[0].url == "https://caa.example.com/wall.jpg"
    assert "Pink Floyd" in artworks[0].label
    assert "The Wall" in artworks[0].label


@patch("mediainfo.idle.library.fetch_front_cover")
def test_caches_cover_url_and_skips_repeat_lookup(mock_fetch, tmp_path):
    library = _library(tmp_path)
    _seed_album(library)
    mock_fetch.return_value = "https://caa.example.com/wall.jpg"

    source = _source(library)
    source.get_wallpapers()
    source.get_wallpapers()

    assert mock_fetch.call_count == 1


@patch("mediainfo.idle.library.fetch_front_cover")
def test_caches_negative_result(mock_fetch, tmp_path):
    library = _library(tmp_path)
    _seed_album(library)
    mock_fetch.return_value = None

    source = _source(library)
    assert source.get_wallpapers() == []
    assert source.get_wallpapers() == []
    assert mock_fetch.call_count == 1


def test_returns_empty_without_library():
    source = LibraryWallpaperSource(LibraryIdleConfig(enabled=True), library=None)
    assert source.get_wallpapers() == []


def test_returns_empty_when_library_has_no_albums(tmp_path):
    library = _library(tmp_path)
    assert _source(library).get_wallpapers() == []


def test_handles_library_exception_gracefully(tmp_path):
    library = _library(tmp_path)
    _seed_album(library)
    library.close()  # subsequent queries will raise

    assert _source(library).get_wallpapers() == []


def test_rotation_interval_set_from_config(tmp_path):
    library = _library(tmp_path)
    source = _source(library, rotation_interval_seconds=600)
    assert source.rotation_interval_seconds == 600
