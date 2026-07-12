"""Tests for the MPD source."""

from typing import Any
from unittest.mock import MagicMock, patch

from mediainfo.config import MpdConfig
from mediainfo.sources.mpd import MpdSource, _ART_CACHE_DIR, _art_cache_path


def _source(**kwargs) -> MpdSource:
    defaults: dict[str, Any] = dict(enabled=True, host="192.168.1.40", port=6600)
    defaults.update(kwargs)
    return MpdSource(MpdConfig(**defaults))


def _client(status=None, song=None, art_error=True):
    client = MagicMock()
    client.status.return_value = status or {"state": "stop"}
    client.currentsong.return_value = song or {}
    if art_error:
        client.readpicture.side_effect = Exception("not supported")
        client.albumart.side_effect = Exception("not supported")
    else:
        client.readpicture.return_value = {}
        client.albumart.return_value = {}
    return client


@patch("mediainfo.sources.mpd.mpd.MPDClient")
def test_stopped_returns_none(mock_cls):
    mock_cls.return_value = _client(status={"state": "stop"})

    source = _source()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is False


@patch("mediainfo.sources.mpd.mpd.MPDClient")
def test_paused_returns_none(mock_cls):
    mock_cls.return_value = _client(status={"state": "pause"})

    source = _source()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is False


@patch("mediainfo.sources.mpd.mpd.MPDClient")
def test_playing_track(mock_cls):
    mock_cls.return_value = _client(
        status={"state": "play", "elapsed": "12.345", "duration": "355.0"},
        song={
            "file": "music/queen/bohemian_rhapsody.mp3",
            "artist": "Queen",
            "album": "A Night at the Opera",
            "title": "Bohemian Rhapsody",
        },
    )

    result = _source().get_now_playing()

    assert result is not None
    assert result.source == "mpd"
    assert result.media_type == "music"
    assert result.title == "Bohemian Rhapsody"
    assert result.subtitle == "Queen"
    assert result.artist == "Queen"
    assert result.album == "A Night at the Opera"
    assert result.position_seconds == 12.345
    assert result.duration_seconds == 355.0
    assert result.images == []


@patch("mediainfo.sources.mpd.mpd.MPDClient")
def test_missing_title_falls_back_to_file(mock_cls):
    mock_cls.return_value = _client(
        status={"state": "play"},
        song={"file": "music/unknown/track01.mp3"},
    )

    result = _source().get_now_playing()

    assert result.title == "music/unknown/track01.mp3"
    assert result.subtitle == ""
    assert result.album == ""


@patch("mediainfo.sources.mpd.mpd.MPDClient")
def test_no_current_song_returns_none(mock_cls):
    mock_cls.return_value = _client(status={"state": "play"}, song={})

    assert _source().get_now_playing() is None


@patch("mediainfo.sources.mpd.mpd.MPDClient")
def test_embedded_picture_is_cached_and_exposed_as_file_url(mock_cls, tmp_path, monkeypatch):
    import mediainfo.sources.mpd as mpd_source

    monkeypatch.setattr(mpd_source, "_ART_CACHE_DIR", tmp_path)

    client = _client(
        status={"state": "play"},
        song={"file": "music/a.mp3", "artist": "A", "title": "T"},
        art_error=False,
    )
    client.readpicture.return_value = {"binary": b"fake-jpeg-bytes"}
    mock_cls.return_value = client

    result = _source().get_now_playing()

    assert len(result.images) == 1
    assert result.images[0].url.startswith("file://")
    cached_path = mpd_source._art_cache_path("music/a.mp3")
    assert cached_path.read_bytes() == b"fake-jpeg-bytes"


@patch("mediainfo.sources.mpd.mpd.MPDClient")
def test_falls_back_to_albumart_when_readpicture_unsupported(mock_cls, tmp_path, monkeypatch):
    import mediainfo.sources.mpd as mpd_source

    monkeypatch.setattr(mpd_source, "_ART_CACHE_DIR", tmp_path)

    client = _client(status={"state": "play"}, song={"file": "music/b.mp3"})
    client.readpicture.side_effect = Exception("unsupported command")
    client.albumart.side_effect = None
    client.albumart.return_value = {"binary": b"cover-bytes"}
    mock_cls.return_value = client

    result = _source().get_now_playing()

    assert len(result.images) == 1
    assert mpd_source._art_cache_path("music/b.mp3").read_bytes() == b"cover-bytes"


@patch("mediainfo.sources.mpd.mpd.MPDClient")
def test_no_artwork_available_is_not_fatal(mock_cls):
    mock_cls.return_value = _client(
        status={"state": "play"}, song={"file": "music/c.mp3"}, art_error=True
    )

    source = _source()
    result = source.get_now_playing()

    assert result is not None
    assert result.images == []
    assert source.last_poll_failed is False


@patch("mediainfo.sources.mpd.mpd.MPDClient")
def test_art_is_only_fetched_once_per_track(mock_cls):
    client = _client(status={"state": "play"}, song={"file": "music/d.mp3"}, art_error=True)
    mock_cls.return_value = client

    source = _source()
    source.get_now_playing()
    source.get_now_playing()

    assert client.readpicture.call_count == 1


@patch("mediainfo.sources.mpd.mpd.MPDClient")
def test_connection_error_sets_last_poll_failed(mock_cls):
    mock_cls.return_value.connect.side_effect = Exception("connection refused")

    source = _source()
    assert source.get_now_playing() is None
    assert source.last_poll_failed is True


@patch("mediainfo.sources.mpd.mpd.MPDClient")
def test_password_sent_when_configured(mock_cls):
    client = _client(status={"state": "stop"})
    mock_cls.return_value = client

    _source(password="secret").get_now_playing()

    client.password.assert_called_once_with("secret")


@patch("mediainfo.sources.mpd.mpd.MPDClient")
def test_no_password_call_when_not_configured(mock_cls):
    client = _client(status={"state": "stop"})
    mock_cls.return_value = client

    _source(password="").get_now_playing()

    client.password.assert_not_called()


@patch("mediainfo.sources.mpd.mpd.MPDClient")
def test_client_is_disconnected_after_poll(mock_cls):
    client = _client(status={"state": "stop"})
    mock_cls.return_value = client

    _source().get_now_playing()

    client.close.assert_called_once()
    client.disconnect.assert_called_once()


def test_config_disabled_by_default():
    assert MpdConfig().enabled is False


def test_config_defaults():
    cfg = MpdConfig()
    assert cfg.host == "localhost"
    assert cfg.port == 6600
    assert cfg.password == ""
    assert cfg.timeout == 5.0


def test_art_cache_path_is_stable_for_same_uri():
    assert _art_cache_path("music/a.mp3") == _art_cache_path("music/a.mp3")


def test_art_cache_path_differs_for_different_uri():
    assert _art_cache_path("music/a.mp3") != _art_cache_path("music/b.mp3")


def test_art_cache_dir_is_under_system_temp():
    import tempfile

    assert str(_ART_CACHE_DIR).startswith(tempfile.gettempdir())
