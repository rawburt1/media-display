"""Tests for the thetvdb.com enricher."""

from unittest.mock import MagicMock, patch

from pixoo_media.config import TheTvDbConfig
from pixoo_media.enrichers.thetvdb import TheTvDbEnricher
from pixoo_media.models import Artwork, NowPlaying

_ARTWORK_TYPES = {
    "data": [
        {"id": 2, "name": "Poster", "recordType": "series"},
        {"id": 3, "name": "Background", "recordType": "series"},
        {"id": 14, "name": "Poster", "recordType": "season"},
    ]
}

_SERIES_ARTWORKS = {
    "data": {
        "artworks": [
            {"type": 2, "image": "https://thetvdb.com/poster-low.jpg", "score": 10},
            {"type": 2, "image": "https://thetvdb.com/poster-high.jpg", "score": 99},
            {"type": 3, "image": "https://thetvdb.com/background.jpg", "score": 50},
            {"type": 14, "image": "https://thetvdb.com/season-poster.jpg", "score": 100},
        ]
    }
}


def _enricher(**kwargs) -> TheTvDbEnricher:
    defaults = dict(enabled=True, api_key="test-key", pin="")
    defaults.update(kwargs)
    return TheTvDbEnricher(TheTvDbConfig(**defaults))


def _now_playing(**kwargs) -> NowPlaying:
    defaults = dict(source="kodi", media_type="episode", title="Pilot", subtitle="S01E01")
    defaults.update(kwargs)
    return NowPlaying(**defaults, ids={"tvdb": "12345"})


def _response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        response.raise_for_status = MagicMock()
    return response


@patch("pixoo_media.enrichers.thetvdb.requests.get")
@patch("pixoo_media.enrichers.thetvdb.requests.post")
def test_adds_poster_and_fanart(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [_response(_ARTWORK_TYPES), _response(_SERIES_ARTWORKS)]

    now_playing = _now_playing()
    _enricher().enrich(now_playing)

    assert [(i.label, i.url) for i in now_playing.images] == [
        ("Poster (TheTVDB)", "https://thetvdb.com/poster-high.jpg"),
        ("Fanart (TheTVDB)", "https://thetvdb.com/background.jpg"),
    ]

    # Logged in with the configured api key.
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"apikey": "test-key"}


@patch("pixoo_media.enrichers.thetvdb.requests.get")
@patch("pixoo_media.enrichers.thetvdb.requests.post")
def test_skips_non_episode(mock_post, mock_get):
    now_playing = _now_playing(media_type="movie", subtitle="")

    _enricher().enrich(now_playing)

    mock_post.assert_not_called()
    mock_get.assert_not_called()
    assert now_playing.images == []


@patch("pixoo_media.enrichers.thetvdb.requests.get")
@patch("pixoo_media.enrichers.thetvdb.requests.post")
def test_no_tvdb_id_skips(mock_post, mock_get):
    now_playing = NowPlaying(
        source="kodi", media_type="episode", title="Pilot", subtitle="S01E01", ids={}
    )

    _enricher().enrich(now_playing)

    mock_post.assert_not_called()
    mock_get.assert_not_called()


@patch("pixoo_media.enrichers.thetvdb.requests.get")
@patch("pixoo_media.enrichers.thetvdb.requests.post")
def test_does_not_duplicate_existing_image(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [_response(_ARTWORK_TYPES), _response(_SERIES_ARTWORKS)]

    now_playing = _now_playing()
    now_playing.images.append(Artwork(url="https://thetvdb.com/poster-high.jpg", label="Poster (Kodi)"))

    _enricher().enrich(now_playing)

    urls = [i.url for i in now_playing.images]
    assert urls.count("https://thetvdb.com/poster-high.jpg") == 1
    assert "https://thetvdb.com/background.jpg" in urls


@patch("pixoo_media.enrichers.thetvdb.requests.get")
@patch("pixoo_media.enrichers.thetvdb.requests.post")
def test_relogs_in_on_401(mock_post, mock_get):
    mock_post.side_effect = [
        _response({"data": {"token": "expired-token"}}),
        _response({"data": {"token": "fresh-token"}}),
    ]
    mock_get.side_effect = [
        _response({}, status_code=401),
        _response(_ARTWORK_TYPES),
        _response(_SERIES_ARTWORKS),
    ]

    now_playing = _now_playing()
    _enricher().enrich(now_playing)

    assert len(now_playing.images) == 2
    assert mock_post.call_count == 2


@patch("pixoo_media.enrichers.thetvdb.requests.get")
@patch("pixoo_media.enrichers.thetvdb.requests.post")
def test_login_failure_returns_gracefully(mock_post, mock_get):
    mock_post.side_effect = Exception("boom")

    now_playing = _now_playing()
    _enricher().enrich(now_playing)

    assert now_playing.images == []


@patch("pixoo_media.enrichers.thetvdb.requests.get")
@patch("pixoo_media.enrichers.thetvdb.requests.post")
def test_series_not_found_returns_gracefully(mock_post, mock_get):
    mock_post.return_value = _response({"data": {"token": "test-token"}})
    mock_get.side_effect = [_response(_ARTWORK_TYPES), _response({}, status_code=404)]

    now_playing = _now_playing()
    _enricher().enrich(now_playing)

    assert now_playing.images == []
