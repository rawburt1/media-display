"""Tests for the Unsplash idle wallpaper source."""

from unittest.mock import MagicMock, patch

from pixoo_media.config import UnsplashWallpaperConfig
from pixoo_media.idle.unsplash import UnsplashWallpaperSource


def _source(**kwargs) -> UnsplashWallpaperSource:
    defaults = dict(
        enabled=True,
        queries="nature, architecture",
        rotation_interval_seconds=300,
        access_key="test-key",
    )
    defaults.update(kwargs)
    return UnsplashWallpaperSource(UnsplashWallpaperConfig(**defaults))


def test_parses_comma_separated_queries():
    source = _source(queries="nature, architecture ,, space")
    assert source.queries == ["nature", "architecture", "space"]


@patch("pixoo_media.idle.unsplash.requests.get")
def test_returns_artwork_from_response(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "urls": {"regular": "https://images.unsplash.com/photo-123"},
        "description": "A scenic mountain",
    }
    mock_get.return_value = mock_response

    source = _source(queries="nature")
    artwork = source.get_wallpaper()

    assert artwork is not None
    assert artwork.url == "https://images.unsplash.com/photo-123"
    assert artwork.label == "Unsplash: A scenic mountain"

    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.unsplash.com/photos/random"
    assert kwargs["params"] == {"query": "nature"}
    assert kwargs["headers"]["Authorization"] == "Client-ID test-key"


@patch("pixoo_media.idle.unsplash.requests.get")
def test_falls_back_to_alt_description(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "urls": {"regular": "https://images.unsplash.com/photo-123"},
        "description": None,
        "alt_description": "a foggy forest",
    }
    mock_get.return_value = mock_response

    artwork = _source(queries="nature").get_wallpaper()

    assert artwork.label == "Unsplash: a foggy forest"


@patch("pixoo_media.idle.unsplash.requests.get")
def test_no_queries_omits_query_param(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"urls": {"regular": "https://images.unsplash.com/photo-123"}}
    mock_get.return_value = mock_response

    source = _source(queries="")
    source.get_wallpaper()

    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {}


@patch("pixoo_media.idle.unsplash.requests.get")
def test_missing_url_returns_none(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"urls": {}}
    mock_get.return_value = mock_response

    assert _source(queries="nature").get_wallpaper() is None


@patch("pixoo_media.idle.unsplash.requests.get")
def test_request_error_returns_none(mock_get):
    mock_get.side_effect = Exception("boom")

    assert _source(queries="nature").get_wallpaper() is None
