"""Tests for the Pexels idle wallpaper source."""

from typing import Any
from unittest.mock import MagicMock, patch

from mediainfo.config import PexelsWallpaperConfig
from mediainfo.idle.pexels import PexelsWallpaperSource


def _source(**kwargs) -> PexelsWallpaperSource:
    defaults: dict[str, Any] = dict(
        enabled=True,
        queries="nature, architecture",
        rotation_interval_seconds=300,
        batch_size=10,
        api_key="test-key",
    )
    defaults.update(kwargs)
    return PexelsWallpaperSource(PexelsWallpaperConfig(**defaults))


def test_parses_comma_separated_queries():
    source = _source(queries="nature, architecture ,, space")
    assert source.queries == ["nature", "architecture", "space"]


@patch("mediainfo.idle.pexels.requests.get")
def test_returns_artworks_from_response(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "photos": [
            {
                "src": {"original": "https://images.pexels.com/photo-123.jpg"},
                "alt": "A scenic mountain",
            },
            {
                "src": {"original": "https://images.pexels.com/photo-456.jpg"},
                "alt": "",
            },
        ]
    }
    mock_get.return_value = mock_response

    source = _source(queries="nature", batch_size=2)
    artworks = source.get_wallpapers()

    assert [a.url for a in artworks] == [
        "https://images.pexels.com/photo-123.jpg",
        "https://images.pexels.com/photo-456.jpg",
    ]
    assert artworks[0].label == "Pexels: A scenic mountain"
    assert artworks[1].label == "Pexels"

    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.pexels.com/v1/search"
    assert kwargs["params"] == {"query": "nature", "per_page": 2}
    assert kwargs["headers"]["Authorization"] == "test-key"


def test_no_queries_returns_empty_list_without_request():
    source = _source(queries="")
    assert source.get_wallpapers() == []


@patch("mediainfo.idle.pexels.requests.get")
def test_photos_without_urls_are_skipped(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "photos": [
            {"src": {}},
            {"src": {"original": "https://images.pexels.com/photo-123.jpg"}},
        ]
    }
    mock_get.return_value = mock_response

    artworks = _source(queries="nature").get_wallpapers()

    assert [a.url for a in artworks] == ["https://images.pexels.com/photo-123.jpg"]


@patch("mediainfo.idle.pexels.requests.get")
def test_request_error_returns_empty_list(mock_get):
    mock_get.side_effect = Exception("boom")

    assert _source(queries="nature").get_wallpapers() == []


@patch("mediainfo.idle.pexels.requests.get")
def test_no_photos_in_response_returns_empty_list(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"photos": []}
    mock_get.return_value = mock_response

    assert _source(queries="nature").get_wallpapers() == []
