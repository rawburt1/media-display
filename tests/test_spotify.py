"""Tests for the Spotify now-playing source."""

from unittest.mock import patch

from mediainfo.config import SpotifyConfig
from mediainfo.sources.spotify import SpotifySource


def _make_config():
    return SpotifyConfig(
        enabled=True,
        client_id="test_client_id",
        client_secret="test_client_secret",
        redirect_uri="http://localhost:8888/callback",
        cache_path="/tmp/test_spotify_cache",
    )


def _valid_token():
    return {"access_token": "tok", "scope": "user-read-playback-state"}


def _make_result(
    is_playing=True,
    kind="track",
    title="Bohemian Rhapsody",
    artist="Queen",
    album="A Night at the Opera",
    image_url="https://example.com/cover.jpg",
    device_name="Kitchen speaker",
    progress_ms=12345,
    duration_ms=354000,
):
    return {
        "is_playing": is_playing,
        "currently_playing_type": kind,
        "device": {"name": device_name} if device_name is not None else None,
        "progress_ms": progress_ms,
        "item": {
            "name": title,
            "artists": [{"name": artist}],
            "album": {
                "name": album,
                "images": [{"url": image_url, "height": 640, "width": 640}],
            },
            "duration_ms": duration_ms,
        },
    }


@patch("mediainfo.sources.spotify.spotipy.Spotify")
@patch("mediainfo.sources.spotify.SpotifyOAuth")
def test_returns_now_playing(MockOAuth, MockSpotify):
    MockOAuth.return_value.get_cached_token.return_value = _valid_token()
    MockSpotify.return_value.current_playback.return_value = _make_result()

    result = SpotifySource(_make_config()).get_now_playing()

    assert result is not None
    assert result.title == "Bohemian Rhapsody"
    assert result.subtitle == "Queen"
    assert result.album == "A Night at the Opera"
    assert result.images[0].url == "https://example.com/cover.jpg"
    assert result.images[0].label == "Album art (Spotify)"
    assert result.source == "spotify"
    assert result.media_type == "music"
    assert result.artist == "Queen"
    assert result.device == "Kitchen speaker"
    assert result.position_seconds == 12.345
    assert result.duration_seconds == 354.0


@patch("mediainfo.sources.spotify.spotipy.Spotify")
@patch("mediainfo.sources.spotify.SpotifyOAuth")
def test_missing_device_defaults_to_empty(MockOAuth, MockSpotify):
    MockOAuth.return_value.get_cached_token.return_value = _valid_token()
    MockSpotify.return_value.current_playback.return_value = _make_result(device_name=None)

    result = SpotifySource(_make_config()).get_now_playing()

    assert result.device == ""


@patch("mediainfo.sources.spotify.spotipy.Spotify")
@patch("mediainfo.sources.spotify.SpotifyOAuth")
def test_missing_progress_and_duration_are_none(MockOAuth, MockSpotify):
    MockOAuth.return_value.get_cached_token.return_value = _valid_token()
    result_data = _make_result(progress_ms=None, duration_ms=None)
    MockSpotify.return_value.current_playback.return_value = result_data

    result = SpotifySource(_make_config()).get_now_playing()

    assert result.position_seconds is None
    assert result.duration_seconds is None


@patch("mediainfo.sources.spotify.SpotifyOAuth")
def test_returns_none_when_no_cached_token(MockOAuth):
    MockOAuth.return_value.get_cached_token.return_value = None

    source = SpotifySource(_make_config())
    result = source.get_now_playing()

    assert result is None
    assert source.last_poll_failed is True


@patch("mediainfo.sources.spotify.SpotifyOAuth")
def test_returns_none_when_cached_token_lacks_playback_state_scope(MockOAuth):
    # A token cached under the old, narrower scope (pre-upgrade) - must be
    # rejected with a clear "re-auth" signal, not a raw API 403.
    MockOAuth.return_value.get_cached_token.return_value = {
        "access_token": "tok",
        "scope": "user-read-currently-playing",
    }

    source = SpotifySource(_make_config())
    result = source.get_now_playing()

    assert result is None
    assert source.last_poll_failed is True


@patch("mediainfo.sources.spotify.spotipy.Spotify")
@patch("mediainfo.sources.spotify.SpotifyOAuth")
def test_returns_none_when_not_playing(MockOAuth, MockSpotify):
    MockOAuth.return_value.get_cached_token.return_value = _valid_token()
    MockSpotify.return_value.current_playback.return_value = _make_result(is_playing=False)

    result = SpotifySource(_make_config()).get_now_playing()

    assert result is None


@patch("mediainfo.sources.spotify.spotipy.Spotify")
@patch("mediainfo.sources.spotify.SpotifyOAuth")
def test_returns_none_when_api_returns_none(MockOAuth, MockSpotify):
    MockOAuth.return_value.get_cached_token.return_value = _valid_token()
    MockSpotify.return_value.current_playback.return_value = None

    result = SpotifySource(_make_config()).get_now_playing()

    assert result is None


@patch("mediainfo.sources.spotify.spotipy.Spotify")
@patch("mediainfo.sources.spotify.SpotifyOAuth")
def test_returns_none_for_podcast_episode(MockOAuth, MockSpotify):
    MockOAuth.return_value.get_cached_token.return_value = _valid_token()
    MockSpotify.return_value.current_playback.return_value = _make_result(kind="episode")

    result = SpotifySource(_make_config()).get_now_playing()

    assert result is None


@patch("mediainfo.sources.spotify.spotipy.Spotify")
@patch("mediainfo.sources.spotify.SpotifyOAuth")
def test_returns_none_on_exception(MockOAuth, MockSpotify):
    MockOAuth.return_value.get_cached_token.return_value = _valid_token()
    MockSpotify.return_value.current_playback.side_effect = RuntimeError("network error")

    source = SpotifySource(_make_config())
    result = source.get_now_playing()

    assert result is None
    assert source.last_poll_failed is True
