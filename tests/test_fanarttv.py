"""Tests for the fanart.tv artwork enricher."""

from unittest.mock import MagicMock, patch

from pixoo_media.config import FanartTvConfig
from pixoo_media.enrichers.fanarttv import FanartTvEnricher
from pixoo_media.models import Artwork, NowPlaying


def _enricher() -> FanartTvEnricher:
    return FanartTvEnricher(FanartTvConfig(enabled=True, api_key="test-key"))


def _movie(**kwargs) -> NowPlaying:
    defaults = dict(
        source="kodi",
        media_type="movie",
        title="Movie",
        ids={"tmdb": "603"},
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def _episode(**kwargs) -> NowPlaying:
    defaults = dict(
        source="kodi",
        media_type="episode",
        title="Show",
        subtitle="S01E01 - Pilot",
        ids={"tvdb": "121361"},
        season=1,
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


@patch("pixoo_media.enrichers.fanarttv.requests.get")
def test_movie_picks_best_poster_and_background(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "movieposter": [
            {"url": "http://fanart.tv/poster-low.jpg", "lang": "en", "likes": "1"},
            {"url": "http://fanart.tv/poster-high.jpg", "lang": "en", "likes": "10"},
            {"url": "http://fanart.tv/poster-foreign.jpg", "lang": "de", "likes": "999"},
        ],
        "moviebackground": [
            {"url": "http://fanart.tv/background.jpg", "lang": "00", "likes": "5"},
        ],
    }
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    now_playing = _movie()
    _enricher().enrich(now_playing)

    urls = [image.url for image in now_playing.images]
    labels = [image.label for image in now_playing.images]

    assert "http://fanart.tv/poster-high.jpg" in urls
    assert "http://fanart.tv/poster-foreign.jpg" not in urls
    assert "http://fanart.tv/background.jpg" in urls
    assert "Poster (fanart.tv)" in labels
    assert "Fanart (fanart.tv)" in labels

    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args[0] == "https://webservice.fanart.tv/v3/movies/603"
    assert kwargs["params"] == {"api_key": "test-key"}


@patch("pixoo_media.enrichers.fanarttv.requests.get")
def test_skips_duplicate_already_in_images(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "movieposter": [
            {"url": "http://existing/poster.jpg", "lang": "en", "likes": "10"},
        ],
        "moviebackground": [],
    }
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    now_playing = _movie(
        images=[Artwork(url="http://existing/poster.jpg", label="Poster (Kodi)")]
    )
    _enricher().enrich(now_playing)

    assert len(now_playing.images) == 1


@patch("pixoo_media.enrichers.fanarttv.requests.get")
def test_movie_without_id_does_nothing(mock_get):
    now_playing = _movie(ids={})
    _enricher().enrich(now_playing)

    assert now_playing.images == []
    mock_get.assert_not_called()


@patch("pixoo_media.enrichers.fanarttv.requests.get")
def test_episode_matches_season_poster(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "tvposter": [
            {"url": "http://fanart.tv/show-poster.jpg", "lang": "en", "likes": "5"},
        ],
        "seasonposter": [
            {"url": "http://fanart.tv/season1.jpg", "lang": "en", "likes": "5", "season": "1"},
            {"url": "http://fanart.tv/season2.jpg", "lang": "en", "likes": "5", "season": "2"},
        ],
        "showbackground": [
            {"url": "http://fanart.tv/show-background.jpg", "lang": "en", "likes": "5"},
        ],
    }
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    now_playing = _episode(season=1)
    _enricher().enrich(now_playing)

    urls = [image.url for image in now_playing.images]
    labels = [image.label for image in now_playing.images]

    assert "http://fanart.tv/season1.jpg" in urls
    assert "http://fanart.tv/show-poster.jpg" not in urls
    assert "http://fanart.tv/show-background.jpg" in urls
    assert "Season poster (fanart.tv)" in labels
    assert "Fanart (fanart.tv)" in labels

    args, _ = mock_get.call_args
    assert args[0] == "https://webservice.fanart.tv/v3/tv/121361"


@patch("pixoo_media.enrichers.fanarttv.requests.get")
def test_episode_falls_back_to_show_poster_without_season_match(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "tvposter": [
            {"url": "http://fanart.tv/show-poster.jpg", "lang": "en", "likes": "5"},
        ],
        "seasonposter": [
            {"url": "http://fanart.tv/season2.jpg", "lang": "en", "likes": "5", "season": "2"},
        ],
        "showbackground": [],
    }
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    now_playing = _episode(season=1)
    _enricher().enrich(now_playing)

    urls = [image.url for image in now_playing.images]
    assert "http://fanart.tv/show-poster.jpg" in urls
    assert "http://fanart.tv/season2.jpg" not in urls


@patch("pixoo_media.enrichers.fanarttv.requests.get")
def test_404_response_does_nothing(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response

    now_playing = _movie()
    _enricher().enrich(now_playing)

    assert now_playing.images == []
