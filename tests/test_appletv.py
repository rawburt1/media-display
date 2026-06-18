"""Tests for the Apple TV source."""

import asyncio
import concurrent.futures
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mediainfo.config import AppleTvConfig
from mediainfo.sources.appletv import AppleTvSource, _enum_name, _map_media_type


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(**kwargs):
    defaults = dict(enabled=True, host="192.168.1.90")
    defaults.update(kwargs)
    return AppleTvConfig(**defaults)


def _state(name="Playing"):
    return SimpleNamespace(name=name)


def _playing(state="Playing", media_type="Music", title="Bohemian Rhapsody",
             artist="Queen", album="A Night at the Opera"):
    return SimpleNamespace(
        device_state=_state(state),
        media_type=_state(media_type),
        title=title,
        artist=artist,
        album=album,
    )


@pytest.fixture(autouse=True)
def no_thread(monkeypatch):
    monkeypatch.setattr("threading.Thread.start", lambda self: None)


def _source(config=None):
    return AppleTvSource(config or _config())


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# _enum_name / _map_media_type utilities
# ---------------------------------------------------------------------------

def test_enum_name_uses_name_attribute():
    assert _enum_name(SimpleNamespace(name="Playing")) == "playing"


def test_enum_name_falls_back_to_str():
    assert _enum_name("Playing") == "playing"


@pytest.mark.parametrize("raw,expected", [
    ("Music", "music"),
    ("Video", "movie"),
    ("Unknown", "movie"),
    ("TV", "episode"),
    ("tvshow", "episode"),
])
def test_map_media_type(raw, expected):
    assert _map_media_type(SimpleNamespace(name=raw)) == expected


# ---------------------------------------------------------------------------
# _fetch — normal playback
# ---------------------------------------------------------------------------

def test_fetch_returns_now_playing_for_music():
    src = _source()
    src._atv = MagicMock()
    src._atv.metadata.playing = AsyncMock(return_value=_playing())

    with patch.object(src, "_fetch_artwork", new=AsyncMock(return_value=None)):
        result = run(src._fetch())

    assert result is not None
    assert result.title == "Bohemian Rhapsody"
    assert result.subtitle == "Queen"
    assert result.album == "A Night at the Opera"
    assert result.media_type == "music"
    assert result.source == "appletv"


def test_fetch_maps_video_to_movie():
    src = _source()
    src._atv = MagicMock()
    src._atv.metadata.playing = AsyncMock(
        return_value=_playing(media_type="Video", title="Inception", artist="", album="")
    )
    with patch.object(src, "_fetch_artwork", new=AsyncMock(return_value=None)):
        result = run(src._fetch())

    assert result is not None
    assert result.media_type == "movie"


def test_fetch_includes_artwork_when_available(tmp_path):
    src = _source()
    src._atv = MagicMock()
    src._atv.metadata.playing = AsyncMock(return_value=_playing())
    art_path = tmp_path / "appletv_abc123.jpg"
    art_path.write_bytes(b"img")

    with patch.object(src, "_fetch_artwork", new=AsyncMock(return_value=art_path)):
        result = run(src._fetch())

    assert len(result.images) == 1
    assert result.images[0].url == art_path.as_uri()
    assert "Apple TV" in result.images[0].label


def test_fetch_returns_none_images_when_no_artwork():
    src = _source()
    src._atv = MagicMock()
    src._atv.metadata.playing = AsyncMock(return_value=_playing())
    with patch.object(src, "_fetch_artwork", new=AsyncMock(return_value=None)):
        result = run(src._fetch())
    assert result.images == []


# ---------------------------------------------------------------------------
# _fetch — not playing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state", ["Paused", "Idle", "Stopped"])
def test_fetch_returns_none_when_not_playing(state):
    src = _source()
    src._atv = MagicMock()
    src._atv.metadata.playing = AsyncMock(return_value=_playing(state=state))
    assert run(src._fetch()) is None


def test_fetch_returns_none_when_title_empty():
    src = _source()
    src._atv = MagicMock()
    src._atv.metadata.playing = AsyncMock(return_value=_playing(title=""))
    assert run(src._fetch()) is None


def test_fetch_returns_none_when_title_none():
    src = _source()
    src._atv = MagicMock()
    src._atv.metadata.playing = AsyncMock(return_value=_playing(title=None))
    assert run(src._fetch()) is None


# ---------------------------------------------------------------------------
# _fetch — connection handling
# ---------------------------------------------------------------------------

def test_fetch_returns_none_when_not_connected_and_scan_finds_nothing():
    src = _source()
    with patch("mediainfo.sources.appletv.pyatv.scan", new=AsyncMock(return_value=[])):
        assert run(src._fetch()) is None


def test_fetch_disconnects_on_playing_exception():
    src = _source()
    src._atv = MagicMock()
    src._atv.metadata.playing = AsyncMock(side_effect=OSError("connection reset"))

    result = run(src._fetch())

    assert result is None
    assert src._atv is None  # disconnected


def test_fetch_connects_and_returns_result_on_fresh_start():
    src = _source()

    mock_atv = MagicMock()
    mock_atv.metadata.playing = AsyncMock(return_value=_playing())
    mock_conf = MagicMock()
    mock_conf.name = "Living Room"

    with (
        patch("mediainfo.sources.appletv.pyatv.scan", new=AsyncMock(return_value=[mock_conf])),
        patch("mediainfo.sources.appletv.pyatv.connect", new=AsyncMock(return_value=mock_atv)),
        patch.object(src, "_fetch_artwork", new=AsyncMock(return_value=None)),
    ):
        result = run(src._fetch())

    assert result is not None
    assert result.title == "Bohemian Rhapsody"


# ---------------------------------------------------------------------------
# _fetch_artwork
# ---------------------------------------------------------------------------

def test_fetch_artwork_writes_bytes_and_returns_path(tmp_path):
    src = _source()
    with patch("mediainfo.sources.appletv._ART_DIR", tmp_path):
        src._atv = MagicMock()
        art_mock = MagicMock()
        art_mock.bytes = b"\xff\xd8\xff" * 100  # fake JPEG
        src._atv.metadata.artwork = AsyncMock(return_value=art_mock)

        path = run(src._fetch_artwork())

    assert path is not None
    assert path.exists()
    assert path.read_bytes() == art_mock.bytes


def test_fetch_artwork_reuses_existing_file(tmp_path):
    src = _source()
    art_bytes = b"\xff\xd8\xff" * 50
    import hashlib
    digest = hashlib.sha256(art_bytes).hexdigest()[:16]
    existing = tmp_path / f"appletv_{digest}.jpg"
    existing.write_bytes(art_bytes)

    with patch("mediainfo.sources.appletv._ART_DIR", tmp_path):
        src._atv = MagicMock()
        art_mock = MagicMock()
        art_mock.bytes = art_bytes
        src._atv.metadata.artwork = AsyncMock(return_value=art_mock)

        path = run(src._fetch_artwork())

    # File was not rewritten (mtime unchanged proves it was not touched)
    assert path == existing


def test_fetch_artwork_returns_none_when_no_artwork():
    src = _source()
    src._atv = MagicMock()
    src._atv.metadata.artwork = AsyncMock(return_value=None)
    assert run(src._fetch_artwork()) is None


def test_fetch_artwork_returns_none_on_exception():
    src = _source()
    src._atv = MagicMock()
    src._atv.metadata.artwork = AsyncMock(side_effect=RuntimeError("no art"))
    assert run(src._fetch_artwork()) is None


# ---------------------------------------------------------------------------
# get_now_playing (synchronous wrapper)
# ---------------------------------------------------------------------------

def test_get_now_playing_returns_none_on_future_error():
    src = _source()
    future = MagicMock()
    future.result.side_effect = concurrent.futures.TimeoutError()

    captured = []
    def _fake_threadsafe(coro, loop):
        captured.append(coro)
        return future

    with patch("asyncio.run_coroutine_threadsafe", side_effect=_fake_threadsafe):
        result = src.get_now_playing()

    for coro in captured:
        coro.close()  # prevent "coroutine was never awaited" RuntimeWarning
    assert result is None


# ---------------------------------------------------------------------------
# ImageCache file:// support (integration with artwork path)
# ---------------------------------------------------------------------------

def test_cache_get_path_handles_file_url(tmp_path):
    from mediainfo.cache import ImageCache
    from mediainfo.models import Artwork

    img = tmp_path / "art.jpg"
    img.write_bytes(b"data")
    cache = ImageCache(tmp_path)
    result = cache.get_path(Artwork(url=img.as_uri()))
    assert result == img


def test_cache_get_path_returns_none_for_missing_file_url(tmp_path):
    from mediainfo.cache import ImageCache
    from mediainfo.models import Artwork

    cache = ImageCache(tmp_path)
    result = cache.get_path(Artwork(url="file:///nonexistent/path/art.jpg"))
    assert result is None
