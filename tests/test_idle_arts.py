"""Tests for the Art Institute of Chicago idle wallpaper source."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mediainfo.config import ArtsWallpaperConfig
from mediainfo.idle.arts import ArtsWallpaperSource
from mediainfo.imaging.transforms import Grayscale


def _source(**kwargs) -> ArtsWallpaperSource:
    defaults: dict[str, Any] = dict(
        enabled=True,
        rotation_interval_seconds=300,
        batch_size=10,
    )
    defaults.update(kwargs)
    return ArtsWallpaperSource(ArtsWallpaperConfig(**defaults))


def _response(data, iiif_url="https://www.artic.edu/iiif/2"):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"config": {"iiif_url": iiif_url}, "data": data}
    return mock_response


@patch("mediainfo.idle.arts.requests.get")
def test_returns_artworks_from_response(mock_get):
    mock_get.return_value = _response(
        [
            {
                "id": 1,
                "title": "Water Lilies",
                "image_id": "abc123",
                "artist_display": "Claude Monet",
                "is_public_domain": True,
            },
            {
                "id": 2,
                "title": "Untitled Study",
                "image_id": "def456",
                "artist_display": "",
                "is_public_domain": True,
            },
        ]
    )

    artworks = _source(batch_size=2).get_wallpapers()

    assert [a.url for a in artworks] == [
        "https://www.artic.edu/iiif/2/abc123/full/843,/0/default.jpg",
        "https://www.artic.edu/iiif/2/def456/full/843,/0/default.jpg",
    ]
    assert artworks[0].label == "Arts: Water Lilies — Claude Monet"
    assert artworks[1].label == "Arts: Untitled Study"
    # The image server 403s hotlinked requests without this - see cache.py.
    assert artworks[0].headers == {"Referer": "https://www.artic.edu/"}


@patch("mediainfo.idle.arts.requests.get")
def test_request_params_include_public_domain_filter_and_batch_size(mock_get):
    mock_get.return_value = _response([])

    _source(batch_size=7).get_wallpapers()

    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.artic.edu/api/v1/artworks/search"
    assert kwargs["params"]["query[term][is_public_domain]"] == "true"
    assert kwargs["params"]["limit"] == 7
    assert 1 <= kwargs["params"]["page"] <= 100


@patch("mediainfo.idle.arts.requests.get")
def test_works_without_image_id_are_skipped(mock_get):
    mock_get.return_value = _response(
        [
            {"id": 1, "title": "No image", "image_id": None, "is_public_domain": True},
            {"id": 2, "title": "Has image", "image_id": "abc123", "is_public_domain": True},
        ]
    )

    artworks = _source().get_wallpapers()

    assert [a.url for a in artworks] == [
        "https://www.artic.edu/iiif/2/abc123/full/843,/0/default.jpg"
    ]


@patch("mediainfo.idle.arts.requests.get")
def test_works_not_public_domain_are_skipped(mock_get):
    mock_get.return_value = _response(
        [{"id": 1, "title": "Restricted", "image_id": "abc123", "is_public_domain": False}]
    )

    assert _source().get_wallpapers() == []


@patch("mediainfo.idle.arts.requests.get")
def test_missing_iiif_url_returns_empty_list(mock_get):
    mock_get.return_value = _response(
        [{"id": 1, "title": "X", "image_id": "abc123", "is_public_domain": True}],
        iiif_url=None,
    )

    assert _source().get_wallpapers() == []


@patch("mediainfo.idle.arts.requests.get")
def test_request_error_returns_empty_list(mock_get):
    mock_get.side_effect = Exception("boom")

    assert _source().get_wallpapers() == []


@patch("mediainfo.idle.arts.requests.get")
def test_malformed_json_returns_empty_list(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.side_effect = ValueError("not json")
    mock_get.return_value = mock_response

    assert _source().get_wallpapers() == []


def test_transform_pipeline_built_from_config():
    source = _source(transforms=[{"grayscale": None}])
    assert len(source.transform_pipeline) == 1
    assert isinstance(source.transform_pipeline[0], Grayscale)


def test_no_transforms_gives_empty_pipeline():
    assert _source().transform_pipeline == []


# ---------------------------------------------------------------------------
# ArtsWallpaperConfig validation (pydantic dataclass, matching every other
# idle source config - see mediainfo/config/idle.py)
# ---------------------------------------------------------------------------


def test_config_unknown_field_raises_validation_error():
    with pytest.raises(ValueError, match="no_such_field"):
        ArtsWallpaperConfig(enabled=True, no_such_field="x")


def test_config_coerces_string_int_batch_size():
    cfg = ArtsWallpaperConfig(enabled=True, batch_size="10")
    assert cfg.batch_size == 10
    assert isinstance(cfg.batch_size, int)
