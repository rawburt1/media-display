"""Tests for the local-folder idle wallpaper source."""

from typing import Any
from pathlib import Path
from urllib.parse import urlparse

from mediainfo.config import LocalWallpaperConfig
from mediainfo.idle.local import LocalWallpaperSource


def _source(base_dir, **kwargs) -> LocalWallpaperSource:
    defaults: dict[str, Any] = dict(
        enabled=True, dir=str(base_dir), rotation_interval_seconds=300, batch_size=15
    )
    defaults.update(kwargs)
    return LocalWallpaperSource(LocalWallpaperConfig(**defaults))


def _make_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake-image-bytes")


def _path_for(artwork) -> Path:
    return Path(urlparse(artwork.url).path)


def test_no_destinations_returns_empty_list(tmp_path):
    source = _source(tmp_path)
    assert source.get_wallpapers() == []


def test_empty_destination_returns_empty_list(tmp_path):
    (tmp_path / "trip1").mkdir()
    source = _source(tmp_path)
    assert source.get_wallpapers() == []


def test_returns_pictures_from_a_single_destination(tmp_path):
    for i in range(5):
        _make_image(tmp_path / "trip1" / f"photo{i}.jpg")
    source = _source(tmp_path, batch_size=15)

    artworks = source.get_wallpapers()

    assert len(artworks) == 5
    for artwork in artworks:
        assert _path_for(artwork).exists()
        assert artwork.label.startswith("trip1: ")


def test_caps_batch_at_batch_size(tmp_path):
    for i in range(20):
        _make_image(tmp_path / "trip1" / f"photo{i}.jpg")
    source = _source(tmp_path, batch_size=15)

    artworks = source.get_wallpapers()

    assert len(artworks) == 15


def test_never_mixes_two_destinations_in_one_batch(tmp_path):
    for i in range(10):
        _make_image(tmp_path / "trip1" / f"photo{i}.jpg")
    for i in range(10):
        _make_image(tmp_path / "trip2" / f"photo{i}.jpg")
    source = _source(tmp_path, batch_size=15)

    artworks = source.get_wallpapers()

    destinations = {artwork.label.split(":")[0] for artwork in artworks}
    assert len(destinations) == 1  # only one destination's pictures, never both


def test_includes_pictures_in_nested_subfolders(tmp_path):
    _make_image(tmp_path / "trip1" / "2022" / "summer" / "photo.jpg")
    source = _source(tmp_path)

    artworks = source.get_wallpapers()

    assert len(artworks) == 1


def test_ignores_non_image_files(tmp_path):
    _make_image(tmp_path / "trip1" / "photo.jpg")
    (tmp_path / "trip1" / "notes.txt").write_text("hello")
    source = _source(tmp_path)

    artworks = source.get_wallpapers()

    assert len(artworks) == 1


def test_ignores_files_directly_under_base_dir_not_in_a_destination(tmp_path):
    (tmp_path / "stray.jpg").write_bytes(b"x")
    _make_image(tmp_path / "trip1" / "photo.jpg")
    source = _source(tmp_path)

    artworks = source.get_wallpapers()

    assert len(artworks) == 1
    assert artworks[0].label.startswith("trip1: ")


def test_missing_base_dir_returns_empty_list(tmp_path):
    source = _source(tmp_path / "does-not-exist")
    assert source.get_wallpapers() == []


def test_urls_are_file_scheme(tmp_path):
    _make_image(tmp_path / "trip1" / "photo.jpg")
    source = _source(tmp_path)

    artworks = source.get_wallpapers()

    assert artworks[0].url.startswith("file://")
