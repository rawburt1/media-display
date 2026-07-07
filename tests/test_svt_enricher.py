"""Tests for the SVT Play enricher."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mediainfo.config import SvtConfig
from mediainfo.enrichers.svt import SvtEnricher, _SONARR_CACHE_TTL, _slugify
from mediainfo.models import Artwork, NowPlaying


def _now_playing(**kwargs):
    defaults: dict[str, Any] = dict(source="shield", media_type="episode", title="Den danska kvinnan", subtitle="5. Brutna ben")
    return NowPlaying(**{**defaults, **kwargs})


def _mock_response(image_id="54285103"):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "data": {
            "contentBySlug": [
                {"images": {"portrait": {"id": image_id}, "wide": {"id": "99999"}}}
            ]
        }
    }
    return mock


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("Den danska kvinnan", "den-danska-kvinnan"),
    ("Finlandsfärjornas försvunna passagerare", "finlandsfarjornas-forsvunna-passagerare"),
    ("Ärliga lögner", "arliga-logner"),
    ("Fröken Julie", "froken-julie"),
    ("Klass 9A", "klass-9a"),
    ("Mästerdetektiven Blomkvist", "masterdetektiven-blomkvist"),
])
def test_slugify(title, expected):
    assert _slugify(title) == expected


# ---------------------------------------------------------------------------
# SvtEnricher.enrich — artwork
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.svt.requests.post")
def test_adds_portrait_image_when_no_other_artwork(mock_post):
    mock_post.return_value = _mock_response("54285103")
    enricher = SvtEnricher(SvtConfig())
    np = _now_playing()

    enricher.enrich(np)

    assert len(np.images) == 1
    assert "54285103" in np.images[0].url
    assert np.images[0].label == "Poster (SVT)"


@patch("mediainfo.enrichers.svt.requests.post")
def test_skips_when_images_already_found(mock_post):
    enricher = SvtEnricher(SvtConfig())
    np = _now_playing()
    np.images.append(Artwork(url="https://example.com/poster.jpg", label="Poster (TheTVDB)"))

    enricher.enrich(np)

    mock_post.assert_not_called()
    assert len(np.images) == 1  # unchanged


@patch("mediainfo.enrichers.svt.requests.post")
def test_skips_svg_lookup_when_tvdb_id_already_set(mock_post):
    enricher = SvtEnricher(SvtConfig())
    np = _now_playing(ids={"tvdb": "12345"})

    enricher.enrich(np)

    mock_post.assert_not_called()


@patch("mediainfo.enrichers.svt.requests.post")
def test_skips_non_episode_media_types(mock_post):
    enricher = SvtEnricher(SvtConfig())

    for media_type in ("music", "movie", "game"):
        np = _now_playing(media_type=media_type)
        enricher.enrich(np)

    mock_post.assert_not_called()


@patch("mediainfo.enrichers.svt.requests.post")
def test_adds_nothing_when_slug_not_found(mock_post):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {"data": {"contentBySlug": []}}
    mock_post.return_value = mock

    enricher = SvtEnricher(SvtConfig())
    np = _now_playing(title="Något okänt program")

    enricher.enrich(np)

    assert np.images == []


@patch("mediainfo.enrichers.svt.requests.post")
def test_falls_back_to_wide_when_portrait_id_missing(mock_post):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "data": {
            "contentBySlug": [
                {"images": {"portrait": {"id": None}, "wide": {"id": "12345"}}}
            ]
        }
    }
    mock_post.return_value = mock

    enricher = SvtEnricher(SvtConfig())
    np = _now_playing()
    enricher.enrich(np)

    assert len(np.images) == 1
    assert "12345" in np.images[0].url


@patch("mediainfo.enrichers.svt.requests.post")
def test_caches_result_to_avoid_repeated_api_calls(mock_post):
    mock_post.return_value = _mock_response()
    enricher = SvtEnricher(SvtConfig())

    enricher.enrich(_now_playing())
    enricher.enrich(_now_playing())

    assert mock_post.call_count == 1


@patch("mediainfo.enrichers.svt.requests.post")
def test_network_error_leaves_images_unchanged(mock_post):
    mock_post.side_effect = Exception("connection refused")
    enricher = SvtEnricher(SvtConfig())
    np = _now_playing()

    enricher.enrich(np)  # must not raise

    assert np.images == []


# ---------------------------------------------------------------------------
# originalProgramTitle (Single type)
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.svt.requests.post")
def test_stores_original_program_title_from_single_type(mock_post):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "data": {
            "contentBySlug": [
                {
                    "originalProgramTitle": "Melody Gardot - The Essential at Olympia Paris",
                    "images": {"portrait": {"id": "12345"}, "wide": {"id": "99999"}},
                }
            ]
        }
    }
    mock_post.return_value = mock

    enricher = SvtEnricher(SvtConfig())
    np = _now_playing(title="Melody Gardot Live at the Olympia")
    enricher.enrich(np)

    assert np.original_title == "Melody Gardot - The Essential at Olympia Paris"
    assert len(np.images) == 1


@patch("mediainfo.enrichers.svt.requests.post")
def test_extracts_artist_from_artist_dash_title_format(mock_post):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "data": {
            "contentBySlug": [
                {
                    "originalProgramTitle": "Melody Gardot - The Essential at Olympia Paris",
                    "images": {"portrait": {"id": "12345"}, "wide": {"id": "99999"}},
                }
            ]
        }
    }
    mock_post.return_value = mock

    enricher = SvtEnricher(SvtConfig())
    np = _now_playing(title="Melody Gardot live på Olympia")
    enricher.enrich(np)

    assert np.artist == "Melody Gardot"


@patch("mediainfo.enrichers.svt.requests.post")
def test_does_not_extract_artist_when_no_dash_in_original_title(mock_post):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "data": {
            "contentBySlug": [
                {
                    "originalProgramTitle": "Some Concert Without A Dash",
                    "images": {"portrait": {"id": "12345"}, "wide": {"id": "99999"}},
                }
            ]
        }
    }
    mock_post.return_value = mock

    enricher = SvtEnricher(SvtConfig())
    np = _now_playing(title="Något konsertprogram")
    enricher.enrich(np)

    assert np.artist == ""


@patch("mediainfo.enrichers.svt.requests.post")
def test_does_not_overwrite_existing_original_title(mock_post):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "data": {
            "contentBySlug": [
                {
                    "originalProgramTitle": "New Title From SVT",
                    "images": {"portrait": {"id": "12345"}, "wide": {"id": "99999"}},
                }
            ]
        }
    }
    mock_post.return_value = mock

    enricher = SvtEnricher(SvtConfig())
    np = _now_playing()
    np.original_title = "Already Set"
    enricher.enrich(np)

    assert np.original_title == "Already Set"


# ---------------------------------------------------------------------------
# Sonarr alternate-title lookup
# ---------------------------------------------------------------------------

def _sonarr_config(**kwargs) -> SvtConfig:
    defaults: dict[str, Any] = dict(enabled=True, sonarr_host="192.168.1.50", sonarr_port=8989, sonarr_api_key="key")
    defaults.update(kwargs)
    return SvtConfig(**defaults)


def _series(title="The Danish Woman", tvdb_id=12345, alternate_titles=None) -> dict:
    return {
        "title": title,
        "tvdbId": tvdb_id,
        "alternateTitles": alternate_titles or [],
    }


def _sonarr_get(data):
    mock = MagicMock()
    mock.json.return_value = data
    mock.raise_for_status = MagicMock()
    return mock


@patch("mediainfo.enrichers.svt.requests.post")
@patch("mediainfo.enrichers.svt.requests.get")
def test_sonarr_sets_tvdb_id_from_alternate_title(mock_get, mock_post):
    mock_get.return_value = _sonarr_get([
        _series(
            title="The Danish Woman",
            tvdb_id=12345,
            alternate_titles=[{"title": "Den danska kvinnan"}],
        )
    ])
    mock_post.return_value = _mock_response()

    enricher = SvtEnricher(_sonarr_config())
    np = _now_playing(title="Den danska kvinnan")
    enricher.enrich(np)

    assert np.ids["tvdb"] == "12345"


@patch("mediainfo.enrichers.svt.requests.post")
@patch("mediainfo.enrichers.svt.requests.get")
def test_sonarr_sets_tvdb_id_from_main_title_match(mock_get, mock_post):
    mock_get.return_value = _sonarr_get([
        _series(title="Den danska kvinnan", tvdb_id=99999)
    ])
    mock_post.return_value = _mock_response()

    enricher = SvtEnricher(_sonarr_config())
    np = _now_playing(title="Den danska kvinnan")
    enricher.enrich(np)

    assert np.ids["tvdb"] == "99999"


@patch("mediainfo.enrichers.svt.requests.get")
def test_sonarr_skips_lookup_when_tvdb_id_already_set(mock_get):
    enricher = SvtEnricher(_sonarr_config())
    np = _now_playing(ids={"tvdb": "existing"})
    enricher.enrich(np)

    mock_get.assert_not_called()


@patch("mediainfo.enrichers.svt.requests.post")
@patch("mediainfo.enrichers.svt.requests.get")
def test_sonarr_leaves_ids_unchanged_when_no_match(mock_get, mock_post):
    mock_get.return_value = _sonarr_get([
        _series(title="Other Show", tvdb_id=11111)
    ])
    mock_post.return_value = _mock_response()

    enricher = SvtEnricher(_sonarr_config())
    np = _now_playing(title="Den danska kvinnan")
    enricher.enrich(np)

    assert "tvdb" not in np.ids


@patch("mediainfo.enrichers.svt.requests.post")
@patch("mediainfo.enrichers.svt.requests.get")
def test_sonarr_error_does_not_propagate(mock_get, mock_post):
    mock_get.side_effect = RuntimeError("connection refused")
    mock_post.return_value = _mock_response()

    enricher = SvtEnricher(_sonarr_config())
    np = _now_playing()
    enricher.enrich(np)  # must not raise

    assert "tvdb" not in np.ids


@patch("mediainfo.enrichers.svt.requests.post")
@patch("mediainfo.enrichers.svt.requests.get")
def test_sonarr_series_list_is_cached(mock_get, mock_post):
    mock_get.return_value = _sonarr_get([])
    mock_post.return_value = _mock_response()

    enricher = SvtEnricher(_sonarr_config())
    enricher.enrich(_now_playing(title="Show A"))
    enricher.enrich(_now_playing(title="Show B"))

    assert mock_get.call_count == 1


@patch("mediainfo.enrichers.svt.time.monotonic")
@patch("mediainfo.enrichers.svt.requests.post")
@patch("mediainfo.enrichers.svt.requests.get")
def test_sonarr_cache_refreshes_after_ttl(mock_get, mock_post, mock_time):
    mock_get.return_value = _sonarr_get([])
    mock_post.return_value = _mock_response()

    enricher = SvtEnricher(_sonarr_config())

    mock_time.return_value = 0.0
    enricher.enrich(_now_playing(title="Show A"))
    assert mock_get.call_count == 1

    mock_time.return_value = _SONARR_CACHE_TTL + 1
    enricher.enrich(_now_playing(title="Show B"))
    assert mock_get.call_count == 2


@patch("mediainfo.enrichers.svt.requests.get")
def test_sonarr_not_called_when_not_configured(mock_get):
    enricher = SvtEnricher(SvtConfig())  # no sonarr_host/api_key
    np = _now_playing()

    with patch("mediainfo.enrichers.svt.requests.post") as mock_post:
        mock_post.return_value = _mock_response()
        enricher.enrich(np)

    mock_get.assert_not_called()


@patch("mediainfo.enrichers.svt.requests.post")
@patch("mediainfo.enrichers.svt.requests.get")
def test_sonarr_match_skips_svg_artwork_lookup(mock_get, mock_post):
    """When Sonarr sets a tvdb-id, the SVT CDN artwork lookup is skipped."""
    mock_get.return_value = _sonarr_get([
        _series(title="Den danska kvinnan", tvdb_id=12345)
    ])

    enricher = SvtEnricher(_sonarr_config())
    np = _now_playing(title="Den danska kvinnan")
    enricher.enrich(np)

    assert np.ids["tvdb"] == "12345"
    mock_post.assert_not_called()
