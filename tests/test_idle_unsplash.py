"""Tests for the Unsplash idle wallpaper source."""

from unittest.mock import MagicMock, patch

from mediainfo.config import UnsplashWallpaperConfig
from mediainfo.idle.unsplash import UnsplashWallpaperSource


def _source(**kwargs) -> UnsplashWallpaperSource:
    defaults = dict(
        enabled=True,
        queries="nature, architecture",
        rotation_interval_seconds=300,
        batch_size=10,
        access_key="test-key",
    )
    defaults.update(kwargs)
    return UnsplashWallpaperSource(UnsplashWallpaperConfig(**defaults))


def test_parses_comma_separated_queries():
    source = _source(queries="nature, architecture ,, space")
    assert source.queries == ["nature", "architecture", "space"]


@patch("mediainfo.idle.unsplash.requests.get")
def test_returns_artworks_from_response(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [
        {
            "urls": {"regular": "https://images.unsplash.com/photo-123"},
            "description": "A scenic mountain",
        },
        {
            "urls": {"regular": "https://images.unsplash.com/photo-456"},
            "description": None,
            "alt_description": "a foggy forest",
        },
    ]
    mock_get.return_value = mock_response

    source = _source(queries="nature", batch_size=2)
    artworks = source.get_wallpapers()

    assert [a.url for a in artworks] == [
        "https://images.unsplash.com/photo-123",
        "https://images.unsplash.com/photo-456",
    ]
    assert artworks[0].label == "Unsplash: A scenic mountain"
    assert artworks[1].label == "Unsplash: a foggy forest"

    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.unsplash.com/photos/random"
    assert kwargs["params"] == {"count": 2, "query": "nature"}
    assert kwargs["headers"]["Authorization"] == "Client-ID test-key"


@patch("mediainfo.idle.unsplash.requests.get")
def test_single_object_response_is_wrapped_in_a_list(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "urls": {"regular": "https://images.unsplash.com/photo-123"},
        "description": "A scenic mountain",
    }
    mock_get.return_value = mock_response

    artworks = _source(queries="nature", batch_size=1).get_wallpapers()

    assert len(artworks) == 1
    assert artworks[0].url == "https://images.unsplash.com/photo-123"


@patch("mediainfo.idle.unsplash.requests.get")
def test_no_queries_omits_query_param(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = []
    mock_get.return_value = mock_response

    source = _source(queries="", batch_size=5)
    source.get_wallpapers()

    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"count": 5}


@patch("mediainfo.idle.unsplash.requests.get")
def test_photos_without_urls_are_skipped(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [
        {"urls": {}},
        {"urls": {"regular": "https://images.unsplash.com/photo-123"}},
    ]
    mock_get.return_value = mock_response

    artworks = _source(queries="nature").get_wallpapers()

    assert [a.url for a in artworks] == ["https://images.unsplash.com/photo-123"]


@patch("mediainfo.idle.unsplash.requests.get")
def test_request_error_returns_empty_list(mock_get):
    mock_get.side_effect = Exception("boom")

    assert _source(queries="nature").get_wallpapers() == []
