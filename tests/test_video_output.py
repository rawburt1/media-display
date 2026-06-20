"""Tests for VideoOutput Flask endpoints and state transitions."""

from pathlib import Path
from unittest.mock import MagicMock, patch


from mediainfo.config import VideoOutputConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.video import VideoOutput
from mediainfo.video.base import VideoClip


def _make_output(**kwargs):
    """Create a VideoOutput with the server thread suppressed."""
    defaults = {"enabled": True, "pexels_api_key": "key"}
    defaults.update(kwargs)
    config = VideoOutputConfig(**defaults)
    with patch("mediainfo.outputs.video.threading.Thread"):
        return VideoOutput(config)


def _client(output):
    return output.app.test_client()


def test_idle_state_by_default():
    output = _make_output()
    resp = _client(output).get("/api/state")
    data = resp.get_json()
    assert data["state"] == "idle"


def test_playing_state_after_update():
    output = _make_output()
    now_playing = NowPlaying(source="kodi", media_type="movie", title="Inception",
                             subtitle="2010", images=[])
    artwork = Artwork(url="https://example.com/poster.jpg", label="Poster")
    image_path = Path("/tmp/poster.jpg")

    output.update(now_playing, artwork, image_path)

    data = _client(output).get("/api/state").get_json()
    assert data["state"] == "playing"
    assert data["title"] == "Inception"
    assert data["subtitle"] == "2010"


def test_playing_state_includes_image_url_when_available(tmp_path):
    output = _make_output()
    artwork_file = tmp_path / "poster.jpg"
    artwork_file.write_bytes(b"fake")
    now_playing = NowPlaying(source="kodi", media_type="movie", title="Alien", images=[])
    artwork = Artwork(url="https://example.com/a.jpg", label="")

    output.update(now_playing, artwork, artwork_file)

    data = _client(output).get("/api/state").get_json()
    assert "image" in data
    assert "/image/current" in data["image"]


def test_playing_state_no_image_key_without_image():
    output = _make_output()
    now_playing = NowPlaying(source="kodi", media_type="movie", title="Alien", images=[])
    artwork = Artwork(url="", label="")

    output.update(now_playing, artwork, None)

    data = _client(output).get("/api/state").get_json()
    assert data["state"] == "playing"
    assert "image" not in data


def test_on_idle_resets_to_idle_state():
    output = _make_output()
    now_playing = NowPlaying(source="kodi", media_type="movie", title="Alien", images=[])
    output.update(now_playing, Artwork(url="", label=""), None)

    output.on_idle()

    data = _client(output).get("/api/state").get_json()
    assert data["state"] == "idle"


def test_videos_endpoint_returns_empty_before_refresh():
    output = _make_output()
    data = _client(output).get("/api/videos").get_json()
    assert data == []


def test_videos_endpoint_returns_clips_after_refresh():
    output = _make_output()
    output._videos = [
        VideoClip(url="https://cdn.pexels.com/a.mp4", label="Pexels: nature"),
        VideoClip(url="https://cdn.pexels.com/b.mp4", label="Pexels: nature"),
    ]

    data = _client(output).get("/api/videos").get_json()

    assert len(data) == 2
    assert data[0]["url"] == "https://cdn.pexels.com/a.mp4"
    assert data[0]["label"] == "Pexels: nature"


def test_image_endpoint_returns_404_when_no_image():
    output = _make_output()
    resp = _client(output).get("/image/current")
    assert resp.status_code == 404


def test_image_endpoint_serves_file(tmp_path):
    output = _make_output()
    f = tmp_path / "cover.jpg"
    f.write_bytes(b"\xff\xd8\xff")  # minimal JPEG header

    now_playing = NowPlaying(source="kodi", media_type="movie", title="X", images=[])
    output.update(now_playing, Artwork(url="", label=""), f)

    resp = _client(output).get("/image/current")
    assert resp.status_code == 200


def test_on_new_item_without_images_sets_idle():
    output = _make_output()
    now_playing = NowPlaying(source="kodi", media_type="movie", title="Alien", images=[])
    output.update(now_playing, Artwork(url="", label=""), None)  # was playing

    no_art = NowPlaying(source="kodi", media_type="movie", title="Blade Runner", images=[])
    output.on_new_item(no_art, MagicMock())

    data = _client(output).get("/api/state").get_json()
    assert data["state"] == "idle"


def test_on_new_item_with_images_stays_playing():
    output = _make_output()
    artwork = Artwork(url="https://example.com/a.jpg", label="")
    np = NowPlaying(source="kodi", media_type="movie", title="Alien", images=[artwork])

    output.on_new_item(np, MagicMock())

    # has images → stays in playing mode (not idle)
    assert not output._is_idle


def test_handles_images_is_false():
    assert VideoOutput.handles_images is False


def test_index_page_returns_html():
    output = _make_output()
    resp = _client(output).get("/")
    assert resp.status_code == 200
    assert b"<video" in resp.data
