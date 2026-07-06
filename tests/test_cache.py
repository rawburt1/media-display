"""Tests for ImageCache."""

import os
import time
from unittest.mock import MagicMock, patch

from mediainfo.cache import ImageCache, flatten_transparency
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
    Image.new("RGB", (640, 480), color="red").save(buf, format="JPEG")

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
    Image.new("RGB", (640, 480), color="red").save(buf, format="JPEG")

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


# ---------------------------------------------------------------------------
# Minimum image size (reject low-res downloads)
# ---------------------------------------------------------------------------

def _jpeg_bytes(width, height):
    import io as _io
    from PIL import Image as _Image

    buf = _io.BytesIO()
    _Image.new("RGB", (width, height), color="blue").save(buf, format="JPEG")
    return buf.getvalue()


@patch("mediainfo.cache.requests.get")
def test_rejects_image_smaller_than_minimum(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = _jpeg_bytes(100, 100)
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/thumb.jpg"))

    assert path is None
    assert list(cache.cache_dir.glob("*.jpg")) == []


@patch("mediainfo.cache.requests.get")
def test_rejects_image_narrower_than_minimum_even_if_tall_enough(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = _jpeg_bytes(200, 1000)
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/tall-but-narrow.jpg"))

    assert path is None


@patch("mediainfo.cache.requests.get")
def test_accepts_image_at_exactly_the_minimum_size(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = _jpeg_bytes(400, 400)
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/exact.jpg"))

    assert path is not None
    assert path.exists()


@patch("mediainfo.cache.requests.get")
def test_accepts_image_larger_than_minimum(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = _jpeg_bytes(1920, 1080)
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/hd.jpg"))

    assert path is not None


@patch("mediainfo.cache.requests.get")
def test_unidentifiable_content_is_not_rejected_for_size(mock_get, tmp_path):
    # Can't determine dimensions (e.g. an unrecognized/corrupt format) -
    # don't block caching over something this check can't actually verify.
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = b"not a real image"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/weird.jpg"))

    assert path is not None
    assert path.exists()


@patch("mediainfo.cache.requests.get")
def test_rejected_image_is_not_cached_so_a_retry_hits_network_again(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = _jpeg_bytes(50, 50)
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    artwork = Artwork(url="http://example.com/thumb.jpg")

    assert cache.get_path(artwork) is None
    assert cache.get_path(artwork) is None
    assert mock_get.call_count == 2  # never cached as a "hit", so re-fetched every time


@patch("mediainfo.cache.requests.get")
def test_minimum_size_is_configurable(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = _jpeg_bytes(200, 200)
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path, min_width=100, min_height=100)
    path = cache.get_path(Artwork(url="http://example.com/small.jpg"))

    assert path is not None  # 200x200 passes a lowered 100x100 minimum


@patch("mediainfo.cache.requests.get")
def test_configured_minimum_still_rejects_below_it(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = _jpeg_bytes(50, 50)
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path, min_width=100, min_height=100)
    path = cache.get_path(Artwork(url="http://example.com/tiny.jpg"))

    assert path is None


@patch("mediainfo.cache.requests.get")
def test_minimum_size_check_disabled_when_zero(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = _jpeg_bytes(10, 10)
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path, min_width=0, min_height=0)
    path = cache.get_path(Artwork(url="http://example.com/tiny.jpg"))

    assert path is not None  # check disabled entirely


# ---------------------------------------------------------------------------
# download_temp: download without caching to disk
# ---------------------------------------------------------------------------

def test_download_temp_returns_none_without_artwork(tmp_path):
    cache = ImageCache(tmp_path)
    assert cache.download_temp(None) is None
    assert cache.download_temp(Artwork(url="")) is None


@patch("mediainfo.cache.requests.get")
def test_download_temp_writes_to_temp_not_cache(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = b"fake-image-bytes"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    path = cache.download_temp(Artwork(url="http://example.com/wallpaper.jpg"))

    assert path is not None
    assert path.exists()
    assert path.read_bytes() == b"fake-image-bytes"
    # Must not be stored in any of the cache subdirectories.
    assert path.parent != cache.cache_dir
    assert path.parent != cache.idle_dir
    assert path.parent != cache.music_dir


@patch("mediainfo.cache.requests.get")
def test_download_temp_always_fetches_from_network(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = b"fake-image-bytes"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    artwork = Artwork(url="http://example.com/wallpaper.jpg")

    path1 = cache.download_temp(artwork)
    path2 = cache.download_temp(artwork)

    assert mock_get.call_count == 2  # no caching: always re-fetches
    # Each call returns a different temp file.
    assert path1 != path2

    # Clean up.
    for p in (path1, path2):
        if p and p.exists():
            p.unlink()


@patch("mediainfo.cache.requests.get")
def test_download_temp_returns_none_for_undersized_image(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = _jpeg_bytes(50, 50)
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    cache = ImageCache(tmp_path)
    path = cache.download_temp(Artwork(url="http://example.com/thumb.jpg"))

    assert path is None


# ---------------------------------------------------------------------------
# JPEG normalization: non-JPEG downloads are converted, JPEGs kept as-is
# ---------------------------------------------------------------------------

def _image_bytes(fmt, size=(640, 480), mode="RGB"):
    import io as _io
    from PIL import Image as _Image

    buf = _io.BytesIO()
    _Image.new(mode, size, color="blue").save(buf, format=fmt)
    return buf.getvalue()


def _mock_response(content, content_type):
    response = MagicMock()
    response.headers = {"Content-Type": content_type}
    response.content = content
    response.raise_for_status = MagicMock()
    return response


@patch("mediainfo.cache.requests.get")
def test_png_download_is_cached_as_jpeg(mock_get, tmp_path):
    from PIL import Image

    mock_get.return_value = _mock_response(_image_bytes("PNG"), "image/png")

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/art.png"))

    assert path.suffix == ".jpg"
    with Image.open(path) as img:
        assert img.format == "JPEG"
        assert img.size == (640, 480)


@patch("mediainfo.cache.requests.get")
def test_webp_download_is_cached_as_jpeg(mock_get, tmp_path):
    from PIL import Image

    mock_get.return_value = _mock_response(_image_bytes("WEBP"), "image/webp")

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/art.webp"))

    assert path.suffix == ".jpg"
    with Image.open(path) as img:
        assert img.format == "JPEG"


@patch("mediainfo.cache.requests.get")
def test_rgba_png_converts_without_error(mock_get, tmp_path):
    # JPEG has no alpha channel - conversion must not raise on RGBA input.
    from PIL import Image

    mock_get.return_value = _mock_response(
        _image_bytes("PNG", mode="RGBA"), "image/png"
    )

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/logo.png"))

    assert path.suffix == ".jpg"
    with Image.open(path) as img:
        assert img.format == "JPEG"


@patch("mediainfo.cache.requests.get")
def test_transparent_png_is_not_flattened_to_black(mock_get, tmp_path):
    # A common real-world pattern (e.g. many Wikipedia/Wikimedia thumbnails):
    # an opaque subject on an otherwise fully transparent background, with
    # the encoder zeroing out RGB under alpha=0. A naive convert("RGB")
    # exposes that zeroed RGB as solid black - this must composite onto a
    # background instead (see flatten_transparency's docstring).
    from PIL import Image
    import io

    img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    for x in range(150, 250):
        for y in range(150, 250):
            img.putpixel((x, y), (200, 30, 30, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    mock_get.return_value = _mock_response(buf.getvalue(), "image/png")

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/wiki-thumb.png"))

    with Image.open(path) as result:
        # A corner, well outside the opaque subject, must be white
        # (background), not black (naive alpha discard).
        assert result.convert("RGB").getpixel((10, 10)) != (0, 0, 0)


def test_flatten_transparency_composites_onto_white():
    from PIL import Image

    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    img.putpixel((5, 5), (10, 20, 30, 255))

    result = flatten_transparency(img)

    assert result.mode == "RGB"
    assert result.getpixel((0, 0)) == (255, 255, 255)
    assert result.getpixel((5, 5)) == (10, 20, 30)


def test_flatten_transparency_is_a_no_op_for_opaque_rgb():
    from PIL import Image

    img = Image.new("RGB", (10, 10), (5, 6, 7))
    result = flatten_transparency(img)
    assert result.getpixel((0, 0)) == (5, 6, 7)


def test_flatten_transparency_handles_paletted_transparency():
    from PIL import Image

    img = Image.new("P", (10, 10))
    img.putpalette([0, 0, 0, 200, 30, 30] + [0] * (256 * 3 - 6))
    img.putpixel((0, 0), 0)  # background palette entry
    img.putpixel((5, 5), 1)  # subject palette entry
    img.info["transparency"] = 0  # palette index 0 is transparent

    result = flatten_transparency(img)

    assert result.mode == "RGB"
    assert result.getpixel((0, 0)) == (255, 255, 255)
    assert result.getpixel((5, 5)) == (200, 30, 30)


@patch("mediainfo.cache.requests.get")
def test_jpeg_download_is_stored_byte_for_byte(mock_get, tmp_path):
    # Already-JPEG content must not be recompressed (quality loss).
    content = _jpeg_bytes(640, 480)
    mock_get.return_value = _mock_response(content, "image/jpeg")

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/art.jpg"))

    assert path.suffix == ".jpg"
    assert path.read_bytes() == content


@patch("mediainfo.cache.requests.get")
def test_undecodable_download_falls_back_to_raw_bytes(mock_get, tmp_path):
    # Content PIL can't open keeps the old behavior: raw bytes, extension
    # from the Content-Type header.
    mock_get.return_value = _mock_response(b"not-an-image", "image/png")

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url="http://example.com/art"))

    assert path.suffix == ".png"
    assert path.read_bytes() == b"not-an-image"


@patch("mediainfo.cache.requests.get")
def test_download_temp_converts_png_to_jpeg(mock_get, tmp_path):
    from PIL import Image

    mock_get.return_value = _mock_response(_image_bytes("PNG"), "image/png")

    cache = ImageCache(tmp_path)
    path = cache.download_temp(Artwork(url="http://example.com/art.png"))

    try:
        assert path.suffix == ".jpg"
        with Image.open(path) as img:
            assert img.format == "JPEG"
    finally:
        path.unlink()


@patch("mediainfo.cache.requests.get")
def test_download_temp_keeps_jpeg_bytes_unchanged(mock_get, tmp_path):
    content = _jpeg_bytes(640, 480)
    mock_get.return_value = _mock_response(content, "image/jpeg")

    cache = ImageCache(tmp_path)
    path = cache.download_temp(Artwork(url="http://example.com/art.jpg"))

    try:
        assert path.read_bytes() == content
    finally:
        path.unlink()


@patch("mediainfo.cache.requests.get")
def test_existing_cached_file_with_other_extension_is_still_found(mock_get, tmp_path):
    # Files cached before JPEG normalization (e.g. key.png) must still
    # resolve without a re-download - lookup is by key, not extension.
    import hashlib

    url = "http://example.com/old.png"
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    old = tmp_path / f"{key}.png"
    old.write_bytes(b"pre-normalization-bytes")

    cache = ImageCache(tmp_path)
    path = cache.get_path(Artwork(url=url))

    assert path == old
    assert mock_get.call_count == 0


# ---------------------------------------------------------------------------
# get_derived_path (generic disk-cached derivative, e.g. Pixoo's LED prep)
# ---------------------------------------------------------------------------

def _save_source_image(path, size=(64, 64), color=(1, 2, 3)):
    from PIL import Image

    Image.new("RGB", size, color).save(path, format="JPEG")
    return path


def test_get_derived_path_builds_once_and_caches(tmp_path):
    from PIL import Image

    original = _save_source_image(tmp_path / "art.jpg")
    cache = ImageCache(tmp_path / "cache")
    calls = []

    def build(img):
        calls.append(1)
        return Image.new("RGB", (16, 16), (9, 9, 9))

    path1 = cache.get_derived_path(original, "abc123", build)
    path2 = cache.get_derived_path(original, "abc123", build)

    assert path1 == path2
    assert path1.suffix == ".png"
    assert len(calls) == 1


def test_get_derived_path_saves_as_png_not_jpeg(tmp_path):
    from PIL import Image

    original = _save_source_image(tmp_path / "art.jpg")
    cache = ImageCache(tmp_path / "cache")

    path = cache.get_derived_path(original, "key1", lambda img: Image.new("RGB", (16, 16)))

    assert path.suffix == ".png"
    assert Image.open(path).format == "PNG"


def test_get_derived_path_different_keys_produce_different_files(tmp_path):
    from PIL import Image

    original = _save_source_image(tmp_path / "art.jpg")
    cache = ImageCache(tmp_path / "cache")

    path1 = cache.get_derived_path(original, "key1", lambda img: Image.new("RGB", (16, 16)))
    path2 = cache.get_derived_path(original, "key2", lambda img: Image.new("RGB", (16, 16)))

    assert path1 != path2


def test_get_derived_path_writes_metadata_sidecar_when_build_returns_a_tuple(tmp_path):
    from PIL import Image

    original = _save_source_image(tmp_path / "art.jpg")
    cache = ImageCache(tmp_path / "cache")

    def build(img):
        return Image.new("RGB", (16, 16)), {"removed_count": 2, "method": "inpaint"}

    path = cache.get_derived_path(original, "key1", build)

    sidecar = path.with_suffix(".json")
    assert sidecar.exists()
    import json

    assert json.loads(sidecar.read_text()) == {"removed_count": 2, "method": "inpaint"}


def test_get_derived_path_no_sidecar_when_build_returns_plain_image(tmp_path):
    from PIL import Image

    original = _save_source_image(tmp_path / "art.jpg")
    cache = ImageCache(tmp_path / "cache")

    path = cache.get_derived_path(original, "key1", lambda img: Image.new("RGB", (16, 16)))

    assert not path.with_suffix(".json").exists()
