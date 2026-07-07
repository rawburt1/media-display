"""Tests for the Sonarr artwork/studio enricher."""

from typing import Any
from unittest.mock import MagicMock, patch

from mediainfo.config import SonarrConfig
from mediainfo.enrichers.sonarr import SonarrEnricher
from mediainfo.models import Artwork, NowPlaying


def _enricher() -> SonarrEnricher:
    return SonarrEnricher(SonarrConfig(enabled=True, host="192.168.1.50", port=8989, api_key="key123"))


def _episode(**kwargs) -> NowPlaying:
    defaults: dict[str, Any] = dict(
        source="kodi",
        media_type="episode",
        title="Breaking Bad",
        subtitle="S01E01 - Pilot",
        ids={"tvdb": "81189"},
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def _series(**kwargs) -> dict:
    defaults = {
        "title": "Breaking Bad",
        "network": "AMC",
        "images": [
            {"coverType": "poster", "remoteUrl": "https://sonarr/poster.jpg"},
            {"coverType": "fanart", "remoteUrl": "https://sonarr/fanart.jpg"},
        ],
    }
    defaults.update(kwargs)
    return defaults


def _response(data):
    mock = MagicMock()
    mock.json.return_value = data
    mock.raise_for_status = MagicMock()
    return mock


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_matches_by_tvdb_id_and_sets_studio_and_images(mock_get):
    mock_get.return_value = _response([_series()])

    now_playing = _episode()
    _enricher().enrich(now_playing)

    assert now_playing.studio == "AMC"
    urls = [img.url for img in now_playing.images]
    assert "https://sonarr/poster.jpg" in urls
    assert "https://sonarr/fanart.jpg" in urls

    args, kwargs = mock_get.call_args
    assert args[0] == "http://192.168.1.50:8989/api/v3/series"
    assert kwargs["params"] == {"tvdbId": "81189"}
    assert kwargs["headers"] == {"X-Api-Key": "key123"}


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_falls_back_to_title_match_without_tvdb_id(mock_get):
    mock_get.return_value = _response([_series(title="Other Show"), _series()])

    now_playing = _episode(ids={})
    _enricher().enrich(now_playing)

    assert now_playing.studio == "AMC"
    args, kwargs = mock_get.call_args
    assert kwargs["params"] is None


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_no_match_does_nothing(mock_get):
    mock_get.return_value = _response([])

    now_playing = _episode()
    _enricher().enrich(now_playing)

    assert now_playing.studio == ""
    assert now_playing.images == []


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_ignores_non_episode_media_type(mock_get):
    now_playing = _episode(media_type="movie")
    _enricher().enrich(now_playing)

    mock_get.assert_not_called()


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_skips_duplicate_already_in_images(mock_get):
    mock_get.return_value = _response([_series()])

    now_playing = _episode(images=[Artwork(url="https://sonarr/poster.jpg", label="Existing")])
    _enricher().enrich(now_playing)

    urls = [img.url for img in now_playing.images]
    assert urls.count("https://sonarr/poster.jpg") == 1


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_does_not_overwrite_existing_studio(mock_get):
    mock_get.return_value = _response([_series()])

    now_playing = _episode(studio="Existing Network")
    _enricher().enrich(now_playing)

    assert now_playing.studio == "Existing Network"


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_api_error_does_not_propagate(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")

    now_playing = _episode()
    _enricher().enrich(now_playing)

    assert now_playing.images == []


# ---------------------------------------------------------------------------
# test_connection (shared ArrEnricher implementation - see also
# test_radarr.py/test_lidarr.py for the same coverage on the other two)
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.arr_base.requests.get")
def test_test_connection_success(mock_get):
    mock_get.return_value.raise_for_status = MagicMock()
    ok, message = _enricher().test_connection()
    assert ok is True
    args, kwargs = mock_get.call_args
    assert args[0] == "http://192.168.1.50:8989/api/v3/system/status"
    assert kwargs["headers"] == {"X-Api-Key": "key123"}


@patch("mediainfo.enrichers.arr_base.requests.get")
def test_test_connection_handles_exception(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")
    ok, message = _enricher().test_connection()
    assert ok is False
    assert "connection refused" in message
