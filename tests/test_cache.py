"""Tests for ImageCache."""

from unittest.mock import MagicMock, patch

from pixoo_media.cache import ImageCache
from pixoo_media.models import Artwork


def test_get_path_returns_none_without_artwork(tmp_path):
    cache = ImageCache(tmp_path)
    assert cache.get_path(None) is None
    assert cache.get_path(Artwork(url="")) is None


@patch("pixoo_media.cache.requests.get")
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
