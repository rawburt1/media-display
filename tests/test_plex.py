"""Tests for the Plex source."""

from unittest.mock import MagicMock, patch

from pixoo_media.config import PlexConfig
from pixoo_media.sources.plex import PlexSource, resolve_plex_image_url


def _source(**kwargs) -> PlexSource:
    defaults = dict(enabled=True, host="192.168.1.22", port=32400, token="test-token")
    defaults.update(kwargs)
    return PlexSource(PlexConfig(**defaults))


def _response(metadata):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"MediaContainer": {"Metadata": metadata}}
    return response


def test_resolve_plex_image_url():
    url = resolve_plex_image_url("192.168.1.22", 32400, "test-token", "/library/metadata/1/thumb/2")

    assert url == "http://192.168.1.22:32400/library/metadata/1/thumb/2?X-Plex-Token=test-token"


@patch("pixoo_media.sources.plex.requests.get")
def test_no_sessions_returns_none(mock_get):
    mock_get.return_value = _response([])

    assert _source().get_now_playing() is None


@patch("pixoo_media.sources.plex.requests.get")
def test_paused_session_returns_none(mock_get):
    mock_get.return_value = _response(
        [{"type": "movie", "title": "Inception", "Player": {"state": "paused"}}]
    )

    assert _source().get_now_playing() is None


@patch("pixoo_media.sources.plex.requests.get")
def test_movie_session(mock_get):
    mock_get.return_value = _response(
        [
            {
                "type": "movie",
                "title": "Inception",
                "year": 2010,
                "thumb": "/library/metadata/1/thumb/123",
                "art": "/library/metadata/1/art/456",
                "Player": {"state": "playing"},
                "Guid": [{"id": "imdb://tt1375666"}, {"id": "tmdb://27205"}],
            }
        ]
    )

    now_playing = _source().get_now_playing()

    assert now_playing.source == "plex"
    assert now_playing.media_type == "movie"
    assert now_playing.title == "Inception"
    assert now_playing.subtitle == ""
    assert now_playing.year == 2010
    assert now_playing.ids == {"imdb": "tt1375666", "tmdb": "27205"}
    assert len(now_playing.images) == 2
    assert now_playing.images[0].url == (
        "http://192.168.1.22:32400/library/metadata/1/thumb/123?X-Plex-Token=test-token"
    )
    assert now_playing.images[0].label == "Poster (Plex)"
    assert now_playing.images[1].url == (
        "http://192.168.1.22:32400/library/metadata/1/art/456?X-Plex-Token=test-token"
    )
    assert now_playing.images[1].label == "Fanart (Plex)"


@patch("pixoo_media.sources.plex.requests.get")
def test_episode_session(mock_get):
    mock_get.return_value = _response(
        [
            {
                "type": "episode",
                "title": "Pilot",
                "grandparentTitle": "Breaking Bad",
                "parentIndex": 1,
                "index": 1,
                "thumb": "/library/metadata/2/thumb/123",
                "grandparentThumb": "/library/metadata/3/thumb/456",
                "art": "/library/metadata/3/art/789",
                "grandparentArt": "/library/metadata/3/art/789",
                "Player": {"state": "playing"},
                "Guid": [{"id": "tvdb://81189"}],
            }
        ]
    )

    now_playing = _source().get_now_playing()

    assert now_playing.media_type == "episode"
    assert now_playing.title == "Breaking Bad"
    assert now_playing.subtitle == 'S01E01 - Pilot'
    assert now_playing.season == 1
    assert now_playing.ids == {"tvdb": "81189"}
    assert len(now_playing.images) == 2
    # Prefers the series poster (grandparentThumb) over the episode's own thumb.
    assert now_playing.images[0].url == (
        "http://192.168.1.22:32400/library/metadata/3/thumb/456?X-Plex-Token=test-token"
    )
    assert now_playing.images[0].label == "Poster (Plex)"
    # Prefers the series fanart (grandparentArt) for the background image.
    assert now_playing.images[1].url == (
        "http://192.168.1.22:32400/library/metadata/3/art/789?X-Plex-Token=test-token"
    )
    assert now_playing.images[1].label == "Fanart (Plex)"


@patch("pixoo_media.sources.plex.requests.get")
def test_music_session(mock_get):
    mock_get.return_value = _response(
        [
            {
                "type": "track",
                "title": "Comfortably Numb",
                "grandparentTitle": "Pink Floyd",
                "parentThumb": "/library/metadata/4/thumb/789",
                "art": "/library/metadata/5/art/789",
                "Player": {"state": "playing"},
            }
        ]
    )

    now_playing = _source().get_now_playing()

    assert now_playing.media_type == "music"
    assert now_playing.title == "Comfortably Numb"
    assert now_playing.subtitle == "Pink Floyd"
    assert len(now_playing.images) == 2
    assert now_playing.images[0].url == (
        "http://192.168.1.22:32400/library/metadata/4/thumb/789?X-Plex-Token=test-token"
    )
    assert now_playing.images[0].label == "Poster (Plex)"
    assert now_playing.images[1].url == (
        "http://192.168.1.22:32400/library/metadata/5/art/789?X-Plex-Token=test-token"
    )
    assert now_playing.images[1].label == "Fanart (Plex)"


@patch("pixoo_media.sources.plex.requests.get")
def test_request_error_returns_none(mock_get):
    mock_get.side_effect = Exception("boom")

    assert _source().get_now_playing() is None
