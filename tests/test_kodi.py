"""Tests for the Kodi source."""

from unittest.mock import MagicMock, patch

from pixoo_media.config import KodiConfig
from pixoo_media.sources.kodi import KodiSource, resolve_kodi_image_url


def test_resolve_kodi_image_url():
    art_path = "image://http%3a%2f%2fexample.com%2fposter.jpg/"

    url = resolve_kodi_image_url("192.168.1.50", 8080, art_path)

    assert url == (
        "http://192.168.1.50:8080/image/"
        "image%3A%2F%2Fhttp%253a%252f%252fexample.com%252fposter.jpg%2F"
    )


def _source(**kwargs) -> KodiSource:
    defaults = dict(enabled=True, host="192.168.1.21", port=8080, username="kodi", password="kodi")
    defaults.update(kwargs)
    return KodiSource(KodiConfig(**defaults))


def _rpc_responses(active_players, item, tvshow_uniqueid=None):
    players_response = MagicMock()
    players_response.json.return_value = {"result": active_players}

    item_response = MagicMock()
    item_response.json.return_value = {"result": {"item": item}}

    responses = [players_response, item_response]

    if item.get("type") == "episode":
        tvshow_response = MagicMock()
        tvshow_response.json.return_value = {
            "result": {"tvshowdetails": {"uniqueid": tvshow_uniqueid or {}}}
        }
        responses.append(tvshow_response)

    return responses


@patch("pixoo_media.sources.kodi.requests.post")
def test_no_active_players_returns_none(mock_post):
    response = MagicMock()
    response.json.return_value = {"result": []}
    mock_post.return_value = response

    assert _source().get_now_playing() is None


@patch("pixoo_media.sources.kodi.requests.post")
def test_movie_item(mock_post):
    mock_post.side_effect = _rpc_responses(
        [{"playerid": 1, "type": "video"}],
        {
            "type": "movie",
            "title": "Inception",
            "year": 2010,
            "art": {
                "poster": "image://poster.jpg/",
                "fanart": "image://fanart.jpg/",
            },
            "uniqueid": {"tmdb": "27205"},
        },
    )

    now_playing = _source().get_now_playing()

    assert now_playing.source == "kodi"
    assert now_playing.media_type == "movie"
    assert now_playing.title == "Inception"
    assert now_playing.subtitle == ""
    assert now_playing.year == 2010
    assert now_playing.ids == {"tmdb": "27205"}
    assert len(now_playing.images) == 2
    assert now_playing.images[0].label == "Poster (Kodi)"
    assert now_playing.images[0].url == resolve_kodi_image_url("192.168.1.21", 8080, "image://poster.jpg/")
    assert now_playing.images[1].label == "Fanart (Kodi)"
    assert now_playing.images[1].url == resolve_kodi_image_url("192.168.1.21", 8080, "image://fanart.jpg/")


@patch("pixoo_media.sources.kodi.requests.post")
def test_episode_item_prefers_series_art(mock_post):
    mock_post.side_effect = _rpc_responses(
        [{"playerid": 1, "type": "video"}],
        {
            "type": "episode",
            "title": "Pilot",
            "showtitle": "Breaking Bad",
            "season": 1,
            "episode": 1,
            "tvshowid": 169,
            "art": {
                "thumb": "image://episode-thumb.jpg/",
                "fanart": "image://episode-fanart.jpg/",
                "tvshow.poster": "image://show-poster.jpg/",
                "tvshow.fanart": "image://show-fanart.jpg/",
            },
            "uniqueid": {"tvdb": "9999999"},
        },
        tvshow_uniqueid={"tvdb": "405535", "tmdb": "128098", "imdb": "tt3960394"},
    )

    now_playing = _source().get_now_playing()

    assert now_playing.media_type == "episode"
    assert now_playing.title == "Breaking Bad"
    assert now_playing.subtitle == "S01E01 - Pilot"
    assert now_playing.season == 1
    assert len(now_playing.images) == 2
    # Prefers the series poster/fanart over the episode's own thumb/fanart.
    assert now_playing.images[0].url == resolve_kodi_image_url("192.168.1.21", 8080, "image://show-poster.jpg/")
    assert now_playing.images[1].url == resolve_kodi_image_url("192.168.1.21", 8080, "image://show-fanart.jpg/")
    # Uses the series-level ids (from VideoLibrary.GetTVShowDetails) for
    # enrichers, not the episode's own uniqueid.
    assert now_playing.ids == {"tvdb": "405535", "tmdb": "128098", "imdb": "tt3960394"}


@patch("pixoo_media.sources.kodi.requests.post")
def test_episode_falls_back_to_episode_uniqueid_if_tvshow_lookup_fails(mock_post):
    mock_post.side_effect = _rpc_responses(
        [{"playerid": 1, "type": "video"}],
        {
            "type": "episode",
            "title": "Pilot",
            "showtitle": "Breaking Bad",
            "season": 1,
            "episode": 1,
            "tvshowid": 169,
            "art": {"thumb": "image://episode-thumb.jpg/"},
            "uniqueid": {"tvdb": "9999999"},
        },
        tvshow_uniqueid={},
    )

    now_playing = _source().get_now_playing()

    assert now_playing.ids == {"tvdb": "9999999"}


@patch("pixoo_media.sources.kodi.requests.post")
def test_music_item(mock_post):
    mock_post.side_effect = _rpc_responses(
        [{"playerid": 0, "type": "audio"}],
        {
            "type": "song",
            "title": "Comfortably Numb",
            "artist": ["Pink Floyd"],
            "art": {
                "thumb": "image://album-art.jpg/",
                "fanart": "image://artist-fanart.jpg/",
            },
        },
    )

    now_playing = _source().get_now_playing()

    assert now_playing.media_type == "music"
    assert now_playing.title == "Comfortably Numb"
    assert now_playing.subtitle == "Pink Floyd"
    assert len(now_playing.images) == 2
    assert now_playing.images[0].label == "Poster (Kodi)"
    assert now_playing.images[1].label == "Fanart (Kodi)"
    assert now_playing.ids == {}


@patch("pixoo_media.sources.kodi.requests.post")
def test_music_item_with_musicbrainz_ids(mock_post):
    mock_post.side_effect = _rpc_responses(
        [{"playerid": 0, "type": "audio"}],
        {
            "type": "song",
            "title": "Comfortably Numb",
            "artist": ["Pink Floyd"],
            "art": {"thumb": "image://album-art.jpg/"},
            "musicbrainzalbumid": "album-mbid",
            "musicbrainzalbumartistid": ["83d91898-7763-47d7-b03b-b92132375c47"],
        },
    )

    now_playing = _source().get_now_playing()

    assert now_playing.ids == {
        "musicbrainzartist": "83d91898-7763-47d7-b03b-b92132375c47",
        "musicbrainzalbum": "album-mbid",
    }


@patch("pixoo_media.sources.kodi.requests.post")
def test_request_error_returns_none(mock_post):
    mock_post.side_effect = Exception("boom")

    assert _source().get_now_playing() is None
