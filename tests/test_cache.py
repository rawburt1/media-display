"""Tests for ImageCache."""

import os
import time
from unittest.mock import MagicMock, patch

from mediainfo.cache import ImageCache
from mediainfo.models import Artwork


def test_get_path_returns_none_without_artwork(tmp_path):
    cache = ImageCache(tmp_path)
    assert cache.get_path(None) is None
    assert cache.get_path(Artwork(url="")) is None


@patch("mediainfo.cache.requests.get")
def test_get_path_downloads_and_caches(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = b"fake-image-bytes"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    artwork = Artwork(url="http://example.com/art.jpg")

    path = cache.get_path(artwork)
    assert path is not None
    assert path.exists()
    assert path.suffix == ".jpg"
    assert path.read_bytes() == b"fake-image-bytes"
    assert mock_get.call_count == 1

    # Second call should hit the cache, not the network.
    path2 = cache.get_path(artwork)
    assert path2 == path
    assert mock_get.call_count == 1


@patch("mediainfo.cache.requests.get")
def test_get_path_sends_a_descriptive_user_agent(mock_get, tmp_path):
    # Some hosts (e.g. Wikimedia, used by the Wikipedia enricher) return 403
    # for the default python-requests User-Agent.
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = b"fake-image-bytes"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    cache.get_path(Artwork(url="http://example.com/art.jpg"))

    _, kwargs = mock_get.call_args
    assert "User-Agent" in kwargs["headers"]
    assert kwargs["headers"]["User-Agent"]


def test_purge_expired_removes_old_files_only(tmp_path):
    cache = ImageCache(tmp_path, max_age_days=30)

    old_file = tmp_path / "old.jpg"
    recent_file = tmp_path / "recent.jpg"
    old_file.write_bytes(b"old")
    recent_file.write_bytes(b"recent")

    old_time = time.time() - 31 * 86400
    os.utime(old_file, (old_time, old_time))

    cache.purge_expired()

    assert not old_file.exists()
    assert recent_file.exists()


# ---------------------------------------------------------------------------
# Idle wallpapers: separate subdirectory, separate (shorter) retention
# ---------------------------------------------------------------------------

@patch("mediainfo.cache.requests.get")
def test_idle_artwork_is_stored_in_idle_subdir(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = b"fake-image-bytes"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/wallpaper.jpg"), tier="idle")

    assert path.parent == cache.idle_dir
    assert path.parent != cache.cache_dir


@patch("mediainfo.cache.requests.get")
def test_non_idle_artwork_is_stored_in_main_dir(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = b"fake-image-bytes"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/poster.jpg"))

    assert path.parent == cache.cache_dir


@patch("mediainfo.cache.requests.get")
def test_idle_and_non_idle_caches_for_same_url_are_independent(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = b"fake-image-bytes"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    artwork = Artwork(url="http://example.com/same-url.jpg")

    non_idle_path = cache.get_path(artwork)
    idle_path = cache.get_path(artwork, tier="idle")

    assert non_idle_path != idle_path
    assert mock_get.call_count == 2  # each fetched independently, not cross-cached


def test_purge_expired_uses_shorter_window_for_idle_dir(tmp_path):
    cache = ImageCache(tmp_path, max_age_days=30, idle_max_age_hours=48)

    old_artwork_file = tmp_path / "old_artwork.jpg"
    old_idle_file = cache.idle_dir / "old_idle.jpg"
    old_artwork_file.write_bytes(b"x")
    old_idle_file.write_bytes(b"x")

    # 3 days old: within max_age_days (30) but past idle_max_age_hours (48h).
    three_days_ago = time.time() - 3 * 86400
    os.utime(old_artwork_file, (three_days_ago, three_days_ago))
    os.utime(old_idle_file, (three_days_ago, three_days_ago))

    cache.purge_expired()

    assert old_artwork_file.exists()  # not yet past 30 days
    assert not old_idle_file.exists()  # past 48 hours


def test_purge_expired_keeps_recent_idle_files(tmp_path):
    cache = ImageCache(tmp_path, idle_max_age_hours=48)
    recent_idle_file = cache.idle_dir / "recent.jpg"
    recent_idle_file.write_bytes(b"x")

    cache.purge_expired()

    assert recent_idle_file.exists()


def test_idle_dir_created_on_init(tmp_path):
    cache = ImageCache(tmp_path)
    assert cache.idle_dir.is_dir()


@patch("mediainfo.cache.requests.get")
def test_get_transformed_path_for_idle_image_stays_in_idle_dir(mock_get, tmp_path):
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="red").save(buf, format="JPEG")

    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = buf.getvalue()
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    original_path = cache.get_path(Artwork(url="http://example.com/wallpaper.jpg"), tier="idle")

    from mediainfo.transforms import Resize
    transformed_path = cache.get_transformed_path(original_path, [Resize(width=5, height=5)])

    assert transformed_path.parent == cache.idle_dir


# ---------------------------------------------------------------------------
# Music artwork: separate subdirectory, never purged
# ---------------------------------------------------------------------------

@patch("mediainfo.cache.requests.get")
def test_permanent_artwork_is_stored_in_music_subdir(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = b"fake-image-bytes"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/album.jpg"), tier="music")

    assert path.parent == cache.music_dir
    assert path.parent != cache.cache_dir


@patch("mediainfo.cache.requests.get")
def test_permanent_and_non_permanent_caches_for_same_url_are_independent(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = b"fake-image-bytes"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    artwork = Artwork(url="http://example.com/same-url.jpg")

    non_permanent_path = cache.get_path(artwork)
    permanent_path = cache.get_path(artwork, tier="music")

    assert non_permanent_path != permanent_path
    assert mock_get.call_count == 2


def test_purge_expired_never_removes_music_files(tmp_path):
    cache = ImageCache(tmp_path, max_age_days=30, idle_max_age_hours=48)

    old_music_file = cache.music_dir / "old_album.jpg"
    old_music_file.write_bytes(b"x")
    ancient = time.time() - 365 * 86400
    os.utime(old_music_file, (ancient, ancient))

    cache.purge_expired()

    assert old_music_file.exists()


def test_music_dir_created_on_init(tmp_path):
    cache = ImageCache(tmp_path)
    assert cache.music_dir.is_dir()


@patch("mediainfo.cache.requests.get")
def test_get_transformed_path_for_music_image_stays_in_music_dir(mock_get, tmp_path):
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="red").save(buf, format="JPEG")

    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = buf.getvalue()
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    original_path = cache.get_path(Artwork(url="http://example.com/album.jpg"), tier="music")

    from mediainfo.transforms import Resize
    transformed_path = cache.get_transformed_path(original_path, [Resize(width=5, height=5)])

    assert transformed_path.parent == cache.music_dir
