"""Tests for the Google Nest Hub (Cast) output."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from pixoo_media.config import NestHubConfig
from pixoo_media.models import Artwork, NowPlaying
from pixoo_media.outputs.nest_hub import NestHubOutput


def _config(**kwargs):
    defaults = dict(
        enabled=True, device_ip="192.168.1.50", server_host="192.168.1.10", server_port=8092
    )
    defaults.update(kwargs)
    return NestHubConfig(**defaults)


def _output(**kwargs):
    with patch("pixoo_media.outputs.nest_hub.threading.Thread"):
        return NestHubOutput(_config(**kwargs))


_NOW_PLAYING = NowPlaying(source="kodi", media_type="movie", title="Inception")
_ARTWORK = Artwork(url="https://example.com/poster.jpg", label="Poster")


@patch("pixoo_media.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_update_casts_image_url(mock_get_cast):
    cast = MagicMock()
    mock_get_cast.return_value = cast

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, Path("/cache/abc123.jpg"))

    mock_get_cast.assert_called_once_with(("192.168.1.50", 8009, None, None, "Nest Hub"))
    cast.wait.assert_called_once()
    url, content_type = cast.media_controller.play_media.call_args[0]
    assert url == "http://192.168.1.10:8092/image/current?v=abc123"
    assert content_type == "image/jpeg"


@patch("pixoo_media.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_update_does_not_recast_same_image(mock_get_cast):
    cast = MagicMock()
    mock_get_cast.return_value = cast

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, Path("/cache/abc123.jpg"))
    output.update(_NOW_PLAYING, _ARTWORK, Path("/cache/abc123.jpg"))

    assert cast.media_controller.play_media.call_count == 1


@patch("pixoo_media.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_update_recasts_when_image_changes(mock_get_cast):
    cast = MagicMock()
    mock_get_cast.return_value = cast

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, Path("/cache/abc123.png"))
    output.update(_NOW_PLAYING, _ARTWORK, Path("/cache/def456.jpg"))

    assert cast.media_controller.play_media.call_count == 2
    first_url, first_type = cast.media_controller.play_media.call_args_list[0][0]
    second_url, second_type = cast.media_controller.play_media.call_args_list[1][0]
    assert first_url == "http://192.168.1.10:8092/image/current?v=abc123"
    assert first_type == "image/png"
    assert second_url == "http://192.168.1.10:8092/image/current?v=def456"
    assert second_type == "image/jpeg"


@patch("pixoo_media.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_connection_error_does_not_raise(mock_get_cast):
    mock_get_cast.side_effect = RuntimeError("connection refused")

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, Path("/cache/abc123.jpg"))  # should not raise


@patch("pixoo_media.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_connection_error_does_not_retry_immediately(mock_get_cast):
    mock_get_cast.side_effect = RuntimeError("connection refused")

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, Path("/cache/abc123.jpg"))
    output.update(_NOW_PLAYING, _ARTWORK, Path("/cache/def456.jpg"))

    assert mock_get_cast.call_count == 1


@patch("pixoo_media.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_on_idle_quits_app_once(mock_get_cast):
    cast = MagicMock()
    mock_get_cast.return_value = cast

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, Path("/cache/abc123.jpg"))
    output.on_idle()
    output.on_idle()

    cast.quit_app.assert_called_once()


@patch("pixoo_media.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_update_after_idle_casts_again(mock_get_cast):
    cast = MagicMock()
    mock_get_cast.return_value = cast

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, Path("/cache/abc123.jpg"))
    output.on_idle()
    output.update(_NOW_PLAYING, _ARTWORK, Path("/cache/abc123.jpg"))

    assert cast.media_controller.play_media.call_count == 2


def test_serves_current_image(tmp_path):
    image = tmp_path / "abc123.jpg"
    image.write_bytes(b"image-bytes")

    output = _output()
    output._image_path = image

    with output.app.test_client() as client:
        response = client.get("/image/current")

    assert response.status_code == 200
    assert response.data == b"image-bytes"


def test_serves_404_before_any_image():
    output = _output()

    with output.app.test_client() as client:
        response = client.get("/image/current")

    assert response.status_code == 404
