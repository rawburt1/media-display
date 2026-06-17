"""Tests for the Spotify now-playing source."""

from unittest.mock import MagicMock, patch

from pixoo_media.config import SpotifyConfig
from pixoo_media.sources.spotify import SpotifySource


def _make_config():
    return SpotifyConfig(
        enabled=True,
        client_id="test_client_id",
        client_secret="test_client_secret",
        redirect_uri="http://localhost:8888/callback",
        cache_path="/tmp/test_spotify_cache",
    )


def _make_result(is_playing=True, kind="track", title="Bohemian Rhapsody",
                 artist="Queen", album="A Night at the Opera",
                 image_url="https://example.com/cover.jpg"):
    return {
        "is_playing": is_playing,
        "currently_playing_type": kind,
        "item": {
            "name": title,
            "artists": [{"name": artist}],
            "album": {
                "name": album,
                "images": [{"url": image_url, "height": 640, "width": 640}],
            },
        },
    }


@patch("pixoo_media.sources.spotify.spotipy.Spotify")
@patch("pixoo_media.sources.spotify.SpotifyOAuth")
def test_returns_now_playing(MockOAuth, MockSpotify):
    MockOAuth.return_value.get_cached_token.return_value = {"access_token": "tok"}
    MockSpotify.return_value.current_user_playing_track.return_value = _make_result()

    result = SpotifySource(_make_config()).get_now_playing()

    assert result is not None
    assert result.title == "Bohemian Rhapsody"
    assert result.subtitle == "Queen"
    assert result.album == "A Night at the Opera"
    assert result.images[0].url == "https://example.com/cover.jpg"
    assert result.images[0].label == "Album art (Spotify)"
    assert result.source == "spotify"
    assert result.media_type == "music"


@patch("pixoo_media.sources.spotify.SpotifyOAuth")
def test_returns_none_when_no_cached_token(MockOAuth):
    MockOAuth.return_value.get_cached_token.return_value = None

    result = SpotifySource(_make_config()).get_now_playing()

    assert result is None


@patch("pixoo_media.sources.spotify.spotipy.Spotify")
@patch("pixoo_media.sources.spotify.SpotifyOAuth")
def test_returns_none_when_not_playing(MockOAuth, MockSpotify):
    MockOAuth.return_value.get_cached_token.return_value = {"access_token": "tok"}
    MockSpotify.return_value.current_user_playing_track.return_value = _make_result(is_playing=False)

    result = SpotifySource(_make_config()).get_now_playing()

    assert result is None


@patch("pixoo_media.sources.spotify.spotipy.Spotify")
@patch("pixoo_media.sources.spotify.SpotifyOAuth")
def test_returns_none_when_api_returns_none(MockOAuth, MockSpotify):
    MockOAuth.return_value.get_cached_token.return_value = {"access_token": "tok"}
    MockSpotify.return_value.current_user_playing_track.return_value = None

    result = SpotifySource(_make_config()).get_now_playing()

    assert result is None


@patch("pixoo_media.sources.spotify.spotipy.Spotify")
@patch("pixoo_media.sources.spotify.SpotifyOAuth")
def test_returns_none_for_podcast_episode(MockOAuth, MockSpotify):
    MockOAuth.return_value.get_cached_token.return_value = {"access_token": "tok"}
    MockSpotify.return_value.current_user_playing_track.return_value = _make_result(kind="episode")

    result = SpotifySource(_make_config()).get_now_playing()

    assert result is None


@patch("pixoo_media.sources.spotify.spotipy.Spotify")
@patch("pixoo_media.sources.spotify.SpotifyOAuth")
def test_returns_none_on_exception(MockOAuth, MockSpotify):
    MockOAuth.return_value.get_cached_token.return_value = {"access_token": "tok"}
    MockSpotify.return_value.current_user_playing_track.side_effect = RuntimeError("network error")

    result = SpotifySource(_make_config()).get_now_playing()

    assert result is None
