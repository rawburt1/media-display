"""Tests for the Last.fm artist image enricher."""

from unittest.mock import MagicMock, patch

import pytest

from mediainfo.config import LastFmConfig
from mediainfo.enrichers.lastfm import LastFmEnricher, _PLACEHOLDER_HASH
from mediainfo.models import Artwork, NowPlaying


def _config(api_key="TEST_KEY"):
    return LastFmConfig(enabled=True, api_key=api_key)


def _music(artist="Queen", title="Bohemian Rhapsody", images=None):
    return NowPlaying(
        source="kodi",
        media_type="music",
        title=title,
        subtitle=artist,
        images=images or [],
    )


def _api_response(images):
    return {"artist": {"name": "Queen", "image": images}}


def _image(size, url):
    return {"size": size, "#text": url}


REAL_URL = "https://lastfm.freetls.fastly.net/i/u/300x300/real_artist_photo.jpg"
PLACEHOLDER_URL = f"https://lastfm.freetls.fastly.net/i/u/300x300/{_PLACEHOLDER_HASH}.png"


def _mock_get(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


@patch("mediainfo.enrichers.lastfm.requests.get")
def test_adds_artist_photo_on_success(mock_get):
    mock_get.return_value = _mock_get(_api_response([
        _image("small", "https://example.com/small.jpg"),
        _image("extralarge", REAL_URL),
    ]))
    enricher = LastFmEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert len(np.images) == 1
    assert np.images[0].url == REAL_URL
    assert "Last.fm" in np.images[0].label
    assert "Queen" in np.images[0].label


@patch("mediainfo.enrichers.lastfm.requests.get")
def test_prefers_larger_size(mock_get):
    mega_url = "https://example.com/mega.jpg"
    mock_get.return_value = _mock_get(_api_response([
        _image("large", "https://example.com/large.jpg"),
        _image("extralarge", "https://example.com/extralarge.jpg"),
        _image("mega", mega_url),
    ]))
    enricher = LastFmEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.images[0].url == mega_url


@patch("mediainfo.enrichers.lastfm.requests.get")
def test_skips_placeholder_image(mock_get):
    mock_get.return_value = _mock_get(_api_response([
        _image("extralarge", PLACEHOLDER_URL),
        _image("mega", PLACEHOLDER_URL),
    ]))
    enricher = LastFmEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.images == []


@patch("mediainfo.enrichers.lastfm.requests.get")
def test_skips_empty_url(mock_get):
    mock_get.return_value = _mock_get(_api_response([
        _image("extralarge", ""),
        _image("mega", ""),
    ]))
    enricher = LastFmEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.images == []


@patch("mediainfo.enrichers.lastfm.requests.get")
def test_falls_back_to_smaller_size_when_large_is_placeholder(mock_get):
    medium_url = "https://example.com/medium.jpg"
    mock_get.return_value = _mock_get(_api_response([
        _image("mega", PLACEHOLDER_URL),
        _image("extralarge", PLACEHOLDER_URL),
        _image("large", PLACEHOLDER_URL),
        _image("medium", medium_url),
    ]))
    enricher = LastFmEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.images[0].url == medium_url


@patch("mediainfo.enrichers.lastfm.requests.get")
def test_does_not_add_duplicate(mock_get):
    mock_get.return_value = _mock_get(_api_response([
        _image("extralarge", REAL_URL),
    ]))
    enricher = LastFmEnricher(_config())
    np = _music(images=[Artwork(url=REAL_URL, label="existing")])

    enricher.enrich(np)

    assert len(np.images) == 1


@patch("mediainfo.enrichers.lastfm.requests.get")
def test_skips_non_music(mock_get):
    enricher = LastFmEnricher(_config())
    np = NowPlaying(source="kodi", media_type="movie", title="Inception", images=[])

    enricher.enrich(np)

    mock_get.assert_not_called()
    assert np.images == []


@patch("mediainfo.enrichers.lastfm.requests.get")
def test_skips_when_no_artist(mock_get):
    enricher = LastFmEnricher(_config())
    np = NowPlaying(source="kodi", media_type="music", title="Unknown", subtitle="", images=[])

    enricher.enrich(np)

    mock_get.assert_not_called()
    assert np.images == []


@patch("mediainfo.enrichers.lastfm.requests.get")
def test_handles_api_error_response(mock_get):
    mock_get.return_value = _mock_get({"error": 6, "message": "Artist not found"})
    enricher = LastFmEnricher(_config())
    np = _music(artist="ZZZ Nonexistent Artist XYZ")

    enricher.enrich(np)

    assert np.images == []


@patch("mediainfo.enrichers.lastfm.requests.get")
def test_handles_network_exception(mock_get):
    mock_get.side_effect = ConnectionError("no network")
    enricher = LastFmEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.images == []


@patch("mediainfo.enrichers.lastfm.requests.get")
def test_passes_autocorrect_param(mock_get):
    mock_get.return_value = _mock_get(_api_response([]))
    enricher = LastFmEnricher(_config())

    enricher.enrich(_music())

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["autocorrect"] == "1"


@patch("mediainfo.enrichers.lastfm.requests.get")
def test_passes_api_key(mock_get):
    mock_get.return_value = _mock_get(_api_response([]))
    enricher = LastFmEnricher(_config(api_key="MY_KEY"))

    enricher.enrich(_music())

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["api_key"] == "MY_KEY"
