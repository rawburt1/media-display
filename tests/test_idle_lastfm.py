"""Tests for the Last.fm scrobble history idle wallpaper source."""

from typing import Any
from unittest.mock import MagicMock, patch

from mediainfo.config import LastFmHistoryConfig
from mediainfo.idle.lastfm import LastFmWallpaperSource


def _source(**kwargs) -> LastFmWallpaperSource:
    defaults: dict[str, Any] = dict(
        enabled=True,
        api_key="test-key",
        username="testuser",
        batch_size=10,
        rotation_interval_seconds=300,
    )
    defaults.update(kwargs)
    return LastFmWallpaperSource(LastFmHistoryConfig(**defaults))


def _image(size, url):
    return {"size": size, "#text": url}


def _track(name="Bohemian Rhapsody", artist="Queen", images=None):
    return {
        "name": name,
        "artist": {"#text": artist},
        "image": images or [_image("extralarge", f"https://example.com/{name}.jpg")],
    }


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


PLACEHOLDER_URL = "https://lastfm.freetls.fastly.net/i/u/300x300/2a96cbd8b46e442fc41c2b86b821562f.png"


@patch("mediainfo.idle.lastfm.requests.get")
def test_returns_artworks_from_recent_tracks(mock_get):
    mock_get.return_value = _mock_response({
        "recenttracks": {"track": [_track(name="Song A", artist="Artist A")]}
    })

    artworks = _source().get_wallpapers()

    assert len(artworks) == 1
    assert artworks[0].url == "https://example.com/Song A.jpg"
    assert "Artist A" in artworks[0].label
    assert "Song A" in artworks[0].label


@patch("mediainfo.idle.lastfm.requests.get")
def test_passes_query_params(mock_get):
    mock_get.return_value = _mock_response({"recenttracks": {"track": []}})

    _source(username="myuser", api_key="mykey", batch_size=5).get_wallpapers()

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["method"] == "user.getrecenttracks"
    assert kwargs["params"]["user"] == "myuser"
    assert kwargs["params"]["api_key"] == "mykey"
    assert kwargs["params"]["limit"] == 5


@patch("mediainfo.idle.lastfm.requests.get")
def test_single_track_dict_is_wrapped_in_a_list(mock_get):
    mock_get.return_value = _mock_response({"recenttracks": {"track": _track()}})

    artworks = _source().get_wallpapers()

    assert len(artworks) == 1


@patch("mediainfo.idle.lastfm.requests.get")
def test_prefers_larger_image_size(mock_get):
    mock_get.return_value = _mock_response({
        "recenttracks": {"track": [_track(images=[
            _image("medium", "https://example.com/medium.jpg"),
            _image("extralarge", "https://example.com/extralarge.jpg"),
        ])]}
    })

    artworks = _source().get_wallpapers()

    assert artworks[0].url == "https://example.com/extralarge.jpg"


@patch("mediainfo.idle.lastfm.requests.get")
def test_skips_placeholder_image(mock_get):
    mock_get.return_value = _mock_response({
        "recenttracks": {"track": [_track(images=[_image("extralarge", PLACEHOLDER_URL)])]}
    })

    assert _source().get_wallpapers() == []


@patch("mediainfo.idle.lastfm.requests.get")
def test_deduplicates_by_album_art_url(mock_get):
    shared_url = "https://example.com/same-album.jpg"
    mock_get.return_value = _mock_response({
        "recenttracks": {"track": [
            _track(name="Track 1", images=[_image("extralarge", shared_url)]),
            _track(name="Track 2", images=[_image("extralarge", shared_url)]),
        ]}
    })

    artworks = _source().get_wallpapers()

    assert len(artworks) == 1


@patch("mediainfo.idle.lastfm.requests.get")
def test_skips_tracks_without_image(mock_get):
    track = _track()
    track["image"] = []
    mock_get.return_value = _mock_response({"recenttracks": {"track": [track]}})

    assert _source().get_wallpapers() == []


@patch("mediainfo.idle.lastfm.requests.get")
def test_api_error_returns_empty_list(mock_get):
    mock_get.return_value = _mock_response({"error": 6, "message": "User not found"})

    assert _source().get_wallpapers() == []


@patch("mediainfo.idle.lastfm.requests.get")
def test_network_exception_returns_empty_list(mock_get):
    mock_get.side_effect = ConnectionError("no network")

    assert _source().get_wallpapers() == []


@patch("mediainfo.idle.lastfm.requests.get")
def test_missing_recenttracks_key_returns_empty_list(mock_get):
    mock_get.return_value = _mock_response({})

    assert _source().get_wallpapers() == []


def test_rotation_interval_seconds_set_from_config():
    source = _source(rotation_interval_seconds=600)
    assert source.rotation_interval_seconds == 600
