"""Tests for the Google Nest Hub (Cast) output."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from mediainfo.config import NestHubConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.nest_hub import NestHubOutput


def _config(**kwargs):
    defaults = dict(enabled=True, device_ip="192.168.1.50", server_host="192.168.1.10")
    defaults.update(kwargs)
    return NestHubConfig(**defaults)


def _output(http_port=8092, **kwargs):
    return NestHubOutput(_config(**kwargs), http_port=http_port)


def _client(output, url_prefix=""):
    """Register output's blueprint on a throwaway local Flask app and
    return a test client against it - the reusable harness every other
    output's tests reuse once converted (H1, see
    docs/architecture-usability-review-2026-07.md). Unlike the real
    SharedHttpServer, this is a plain app with no install_auth() wired in,
    since these tests care about routing/behavior, not auth - see
    tests/test_http_server.py for auth coverage.
    """
    app = Flask(__name__)
    app.register_blueprint(output.build_http_blueprint(url_prefix), url_prefix=url_prefix or None)
    return app.test_client()


def _img(tmp_path: Path, name: str) -> Path:
    """Create a minimal real file so image_path.read_bytes() succeeds."""
    p = tmp_path / name
    p.write_bytes(b"x")
    return p


_NOW_PLAYING = NowPlaying(source="kodi", media_type="movie", title="Inception")
_ARTWORK = Artwork(url="https://example.com/poster.jpg", label="Poster")


@patch("mediainfo.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_update_casts_image_url(mock_get_cast, tmp_path):
    cast = MagicMock()
    mock_get_cast.return_value = cast

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "abc123.jpg"))

    mock_get_cast.assert_called_once_with(("192.168.1.50", 8009, None, None, "Nest Hub"))
    cast.wait.assert_called_once()
    url, content_type = cast.media_controller.play_media.call_args[0]
    assert url == "http://192.168.1.10:8092/image/current?v=abc123"
    assert content_type == "image/jpeg"


@patch("mediainfo.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_update_does_not_recast_same_image(mock_get_cast, tmp_path):
    cast = MagicMock()
    mock_get_cast.return_value = cast

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "abc123.jpg"))
    output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "abc123.jpg"))

    assert cast.media_controller.play_media.call_count == 1


@patch("mediainfo.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_update_recasts_when_image_changes(mock_get_cast, tmp_path):
    cast = MagicMock()
    mock_get_cast.return_value = cast

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "abc123.png"))
    output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "def456.jpg"))

    assert cast.media_controller.play_media.call_count == 2
    first_url, first_type = cast.media_controller.play_media.call_args_list[0][0]
    second_url, second_type = cast.media_controller.play_media.call_args_list[1][0]
    assert first_url == "http://192.168.1.10:8092/image/current?v=abc123"
    assert first_type == "image/png"
    assert second_url == "http://192.168.1.10:8092/image/current?v=def456"
    assert second_type == "image/jpeg"


@patch("mediainfo.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_connection_error_propagates(mock_get_cast, tmp_path):
    # So the orchestrator's _call_output() can record it for health/
    # alerting - see orchestrator.py:_call_output.
    mock_get_cast.side_effect = RuntimeError("connection refused")

    output = _output()
    with pytest.raises(ConnectionError):
        output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "abc123.jpg"))


@patch("mediainfo.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_wait_failure_disconnects_the_half_connected_cast(mock_get_cast, tmp_path):
    # get_chromecast_from_host() already spun up the Chromecast's
    # background SocketClient thread before .wait() times out - dropping
    # it without disconnect() would leak that thread's socketpair forever
    # (the file-descriptor leak this fix addresses).
    cast = MagicMock()
    cast.wait.side_effect = RuntimeError("timed out")
    mock_get_cast.return_value = cast

    output = _output()
    with pytest.raises(ConnectionError):
        output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "abc123.jpg"))

    cast.disconnect.assert_called_once()


@patch("mediainfo.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_play_media_failure_disconnects_the_stale_cast(mock_get_cast, tmp_path):
    cast = MagicMock()
    mock_get_cast.return_value = cast

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "abc123.jpg"))

    cast.media_controller.play_media.side_effect = RuntimeError("connection lost")
    with pytest.raises(RuntimeError):
        output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "def456.jpg"))

    cast.disconnect.assert_called_once()
    assert output._cast is None


@patch("mediainfo.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_quit_app_failure_disconnects_the_stale_cast(mock_get_cast, tmp_path):
    cast = MagicMock()
    mock_get_cast.return_value = cast

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "abc123.jpg"))

    cast.quit_app.side_effect = RuntimeError("connection lost")
    with pytest.raises(RuntimeError):
        output.on_idle()

    cast.disconnect.assert_called_once()
    assert output._cast is None


@patch("mediainfo.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_connection_error_does_not_retry_immediately(mock_get_cast, tmp_path):
    mock_get_cast.side_effect = RuntimeError("connection refused")

    output = _output()
    with pytest.raises(ConnectionError):
        output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "abc123.jpg"))
    with pytest.raises(ConnectionError):
        output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "def456.jpg"))

    assert mock_get_cast.call_count == 1


@patch("mediainfo.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_on_idle_quits_app_once(mock_get_cast, tmp_path):
    cast = MagicMock()
    mock_get_cast.return_value = cast

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "abc123.jpg"))
    output.on_idle()
    output.on_idle()

    cast.quit_app.assert_called_once()


@patch("mediainfo.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_update_after_idle_casts_again(mock_get_cast, tmp_path):
    cast = MagicMock()
    mock_get_cast.return_value = cast

    output = _output()
    output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "abc123.jpg"))
    output.on_idle()
    output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "abc123.jpg"))

    assert cast.media_controller.play_media.call_count == 2


def test_serves_current_image(tmp_path):
    image = tmp_path / "current.jpg"
    image.write_bytes(b"image-bytes")

    output = _output()
    output._stable_path = image
    output._stable_content_type = "image/jpeg"

    response = _client(output).get("/image/current")

    assert response.status_code == 200
    assert response.data == b"image-bytes"


def test_serves_404_before_any_image():
    output = _output()

    response = _client(output).get("/image/current")

    assert response.status_code == 404


def test_blueprint_is_reachable_under_its_computed_prefix(tmp_path):
    image = tmp_path / "current.jpg"
    image.write_bytes(b"image-bytes")

    output = _output()
    output._stable_path = image
    output._stable_content_type = "image/jpeg"

    response = _client(output, url_prefix="/nest_hub").get("/nest_hub/image/current")

    assert response.status_code == 200


@patch("mediainfo.outputs.nest_hub.pychromecast.get_chromecast_from_host")
def test_cast_url_includes_the_computed_prefix(mock_get_cast, tmp_path):
    cast = MagicMock()
    mock_get_cast.return_value = cast

    output = _output()
    output.build_http_blueprint("/nest_hub")  # wiring.py calls this before any update()
    output.update(_NOW_PLAYING, _ARTWORK, _img(tmp_path, "abc123.jpg"))

    url, _ = cast.media_controller.play_media.call_args[0]
    assert url == "http://192.168.1.10:8092/nest_hub/image/current?v=abc123"
