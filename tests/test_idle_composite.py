"""Tests for CompositeIdleWallpaperSource, which merges multiple idle
wallpaper sources into a single pool."""

from unittest.mock import MagicMock

from mediainfo.idle.composite import CompositeIdleWallpaperSource
from mediainfo.models import Artwork


def _fake_source(images, rotation_interval_seconds=300):
    source = MagicMock()
    source.rotation_interval_seconds = rotation_interval_seconds
    source.get_wallpapers.return_value = images
    return source


def test_rotation_interval_is_the_minimum_of_all_sources():
    a = _fake_source([], rotation_interval_seconds=300)
    b = _fake_source([], rotation_interval_seconds=60)
    composite = CompositeIdleWallpaperSource([a, b])
    assert composite.rotation_interval_seconds == 60


def test_get_wallpapers_merges_all_sources_on_first_call():
    a_images = [Artwork(url="https://example.com/a.jpg", label="A")]
    b_images = [Artwork(url="https://example.com/b.jpg", label="B")]
    a = _fake_source(a_images)
    b = _fake_source(b_images)
    composite = CompositeIdleWallpaperSource([a, b])

    result = composite.get_wallpapers()

    assert result == a_images + b_images
    a.get_wallpapers.assert_called_once()
    b.get_wallpapers.assert_called_once()


def test_keeps_previous_batch_from_a_source_whose_interval_has_not_elapsed(monkeypatch):
    times = iter([1000.0, 1005.0])
    monkeypatch.setattr("mediainfo.idle.composite.time.monotonic", lambda: next(times))

    a_images = [Artwork(url="https://example.com/a.jpg", label="A")]
    a = _fake_source(a_images, rotation_interval_seconds=1000)
    composite = CompositeIdleWallpaperSource([a])

    first = composite.get_wallpapers()
    second = composite.get_wallpapers()

    assert first == a_images
    assert second == a_images
    a.get_wallpapers.assert_called_once()


def test_refetches_a_source_once_its_own_interval_elapses(monkeypatch):
    times = iter([1000.0, 2001.0])
    monkeypatch.setattr("mediainfo.idle.composite.time.monotonic", lambda: next(times))

    a = _fake_source([Artwork(url="https://example.com/a1.jpg", label="A1")], rotation_interval_seconds=1000)
    composite = CompositeIdleWallpaperSource([a])

    composite.get_wallpapers()
    a.get_wallpapers.return_value = [Artwork(url="https://example.com/a2.jpg", label="A2")]
    result = composite.get_wallpapers()

    assert result == [Artwork(url="https://example.com/a2.jpg", label="A2")]
    assert a.get_wallpapers.call_count == 2


def test_keeps_stale_cache_when_a_source_returns_empty():
    a_images = [Artwork(url="https://example.com/a.jpg", label="A")]
    a = _fake_source(a_images, rotation_interval_seconds=0)
    composite = CompositeIdleWallpaperSource([a])

    first = composite.get_wallpapers()
    a.get_wallpapers.return_value = []
    second = composite.get_wallpapers()

    assert first == a_images
    assert second == a_images
