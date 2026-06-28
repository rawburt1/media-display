"""Tests for the fingerprint enricher."""

import time
from unittest.mock import MagicMock, patch

from mediainfo.config import FingerprintConfig
from mediainfo.enrichers.fingerprint import FingerprintEnricher
from mediainfo.models import Artwork, NowPlaying


def _config(**kwargs):
    return FingerprintConfig(enabled=True, host="localhost", port=8091, **kwargs)


def _music(title="", artist="", images=None):
    return NowPlaying(
        source="sonos", media_type="music", title=title, subtitle=artist, images=images or []
    )


def _response(title="Yesterday", artist="The Beatles", album="Help!", artwork_url="", recognized_at=None):
    data = {"title": title, "artist": artist, "album": album, "artwork_url": artwork_url}
    if recognized_at is not None:
        data["recognized_at"] = recognized_at
    return data


def _mock_get(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


@patch("mediainfo.enrichers.fingerprint.requests.get")
def test_fills_in_artist_and_title(mock_get):
    mock_get.return_value = _mock_get(_response(recognized_at=time.time()))
    enricher = FingerprintEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.subtitle == "The Beatles"
    assert np.title == "Yesterday"
    assert np.album == "Help!"


@patch("mediainfo.enrichers.fingerprint.requests.get")
def test_does_not_overwrite_existing_artist(mock_get):
    mock_get.return_value = _mock_get(_response(recognized_at=time.time()))
    enricher = FingerprintEnricher(_config())
    np = _music(artist="Queen")

    enricher.enrich(np)

    mock_get.assert_not_called()
    assert np.subtitle == "Queen"


@patch("mediainfo.enrichers.fingerprint.requests.get")
def test_skips_non_music(mock_get):
    enricher = FingerprintEnricher(_config())
    np = NowPlaying(source="kodi", media_type="episode", title="Breaking Bad", images=[])

    enricher.enrich(np)

    mock_get.assert_not_called()


@patch("mediainfo.enrichers.fingerprint.requests.get")
def test_adds_artwork_url(mock_get):
    mock_get.return_value = _mock_get(
        _response(artwork_url="https://example.com/cover.jpg", recognized_at=time.time())
    )
    enricher = FingerprintEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert len(np.images) == 1
    assert np.images[0].url == "https://example.com/cover.jpg"
    assert "fingerprint" in np.images[0].label


@patch("mediainfo.enrichers.fingerprint.requests.get")
def test_does_not_add_duplicate_artwork(mock_get):
    url = "https://example.com/cover.jpg"
    mock_get.return_value = _mock_get(_response(artwork_url=url, recognized_at=time.time()))
    enricher = FingerprintEnricher(_config())
    np = _music(images=[Artwork(url=url, label="existing")])
    np.subtitle = ""  # no artist, should still try

    enricher.enrich(np)

    assert np.subtitle == "The Beatles"
    assert len(np.images) == 1  # no duplicate


@patch("mediainfo.enrichers.fingerprint.requests.get")
def test_ignores_stale_result(mock_get):
    stale_time = time.time() - 300
    mock_get.return_value = _mock_get(_response(recognized_at=stale_time))
    enricher = FingerprintEnricher(_config(max_age_seconds=120))
    np = _music()

    enricher.enrich(np)

    assert np.subtitle == ""
    assert np.title == ""


@patch("mediainfo.enrichers.fingerprint.requests.get")
def test_accepts_result_without_timestamp(mock_get):
    mock_get.return_value = _mock_get(_response())  # no recognized_at
    enricher = FingerprintEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.subtitle == "The Beatles"


@patch("mediainfo.enrichers.fingerprint.requests.get")
def test_empty_now_playing_response_does_nothing(mock_get):
    mock_get.return_value = _mock_get({})
    enricher = FingerprintEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.subtitle == ""
    assert np.images == []


@patch("mediainfo.enrichers.fingerprint.requests.get")
def test_network_error_does_nothing(mock_get):
    mock_get.side_effect = ConnectionError("no route to host")
    enricher = FingerprintEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.subtitle == ""
    assert np.images == []


@patch("mediainfo.enrichers.fingerprint.requests.get")
def test_does_not_overwrite_existing_title(mock_get):
    mock_get.return_value = _mock_get(_response(title="Identified Song", recognized_at=time.time()))
    enricher = FingerprintEnricher(_config())
    np = _music(title="Radio Station Name")

    enricher.enrich(np)

    assert np.title == "Radio Station Name"
    assert np.subtitle == "The Beatles"
