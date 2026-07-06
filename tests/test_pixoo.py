"""Tests for the Pixoo output: HTTP payload construction, scheduling, and
disk-caching of the LED-prepared derivative (see mediainfo/led_image.py for
the pipeline itself, tested in test_led_image.py)."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from mediainfo.cache import ImageCache
from mediainfo.config import PixooConfig
from mediainfo.outputs.pixoo import PixooOutput, _save_preview


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(**kwargs):
    defaults = dict(enabled=True, ip="192.168.1.32")
    defaults.update(kwargs)
    return PixooConfig(**defaults)


def _cache(tmp_path: Path) -> ImageCache:
    return ImageCache(tmp_path / "cache")


def _now_playing():
    from mediainfo.models import NowPlaying

    return NowPlaying(source="kodi", media_type="music", title="Test")


def _artwork():
    from mediainfo.models import Artwork

    return Artwork(url="http://example.com/art.jpg")


def _solid_image(width=600, height=600, color=(200, 100, 50)):
    return Image.new("RGB", (width, height), color)


def _save_image(path: Path, width=600, height=600, color=(200, 100, 50)) -> Path:
    img = _solid_image(width, height, color)
    img.save(path, format="JPEG")
    return path


# ---------------------------------------------------------------------------
# _save_preview
# ---------------------------------------------------------------------------

def test_save_preview_writes_512x512_png(tmp_path):
    img = _solid_image(64, 64)
    path = tmp_path / "preview.png"
    _save_preview(img, path)
    assert path.exists()
    preview = Image.open(path)
    assert preview.size == (512, 512)


def test_save_preview_creates_parent_dirs(tmp_path):
    img = _solid_image(64, 64)
    path = tmp_path / "subdir" / "deep" / "preview.png"
    _save_preview(img, path)
    assert path.exists()


def test_save_preview_uses_nearest_neighbour(tmp_path):
    img = Image.new("RGB", (64, 64), (255, 0, 0))
    path = tmp_path / "preview.png"
    _save_preview(img, path)
    preview = Image.open(path).convert("RGB")
    pixels = [preview.getpixel((x, y)) for x in range(512) for y in range(512)]
    assert all(p[0] == 255 and p[1] == 0 and p[2] == 0 for p in pixels)


def test_save_preview_does_not_raise_on_bad_path(tmp_path):
    img = _solid_image(64, 64)
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o444)
    _save_preview(img, ro / "preview.png")  # must not raise
    ro.chmod(0o755)


# ---------------------------------------------------------------------------
# PixooOutput.update — integration
# ---------------------------------------------------------------------------

def test_update_sends_correct_commands(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config(), _cache(tmp_path))

    with patch.object(output, "_post") as mock_post:
        output.update(_now_playing(), _artwork(), img_path)

    assert mock_post.call_count == 2
    commands = [c.args[0]["Command"] for c in mock_post.call_args_list]
    assert commands == ["Draw/ResetHttpGifId", "Draw/SendHttpGif"]


def test_update_sends_64x64_pixels(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config(), _cache(tmp_path))

    sent_payloads = []
    with patch.object(output, "_post", side_effect=lambda p: sent_payloads.append(p)):
        output.update(_now_playing(), _artwork(), img_path)

    gif_payload = next(p for p in sent_payloads if p.get("Command") == "Draw/SendHttpGif")
    raw = base64.b64decode(gif_payload["PicData"])
    assert len(raw) == 64 * 64 * 3  # RGB bytes
    assert gif_payload["PicWidth"] == 64


def test_update_sends_16x16_pixels_when_size_16(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config(size=16), _cache(tmp_path))

    sent_payloads = []
    with patch.object(output, "_post", side_effect=lambda p: sent_payloads.append(p)):
        output.update(_now_playing(), _artwork(), img_path)

    gif_payload = next(p for p in sent_payloads if p.get("Command") == "Draw/SendHttpGif")
    raw = base64.b64decode(gif_payload["PicData"])
    assert len(raw) == 16 * 16 * 3  # RGB bytes
    assert gif_payload["PicWidth"] == 16


def test_update_saves_preview_when_configured(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    preview_path = tmp_path / "preview.png"
    output = PixooOutput(_config(preview_path=str(preview_path)), _cache(tmp_path))

    with patch.object(output, "_post"):
        output.update(_now_playing(), _artwork(), img_path)

    assert preview_path.exists()
    assert Image.open(preview_path).size == (512, 512)


def test_update_no_preview_when_not_configured(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config(), _cache(tmp_path))  # no preview_path

    with patch.object(output, "_post"), patch("mediainfo.outputs.pixoo._save_preview") as mock_prev:
        output.update(_now_playing(), _artwork(), img_path)

    mock_prev.assert_not_called()


def test_update_does_not_raise_on_network_error(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config(), _cache(tmp_path))

    with patch.object(output, "_post", side_effect=OSError("connection refused")):
        output.update(_now_playing(), _artwork(), img_path)  # must not raise


def test_update_does_not_raise_on_bad_image(tmp_path):
    bad_path = tmp_path / "bad.jpg"
    bad_path.write_bytes(b"not an image")
    output = PixooOutput(_config(), _cache(tmp_path))

    with patch.object(output, "_post"):
        output.update(_now_playing(), _artwork(), bad_path)  # must not raise


# ---------------------------------------------------------------------------
# Disk caching of the LED-prepared derivative
# ---------------------------------------------------------------------------

def test_update_only_prepares_image_once_for_repeated_calls(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config(), _cache(tmp_path))

    with patch.object(output, "_post"), patch(
        "mediainfo.outputs.pixoo.prepare_led_image", side_effect=_passthrough_prepare
    ) as mock_prepare:
        output.update(_now_playing(), _artwork(), img_path)
        output.update(_now_playing(), _artwork(), img_path)

    assert mock_prepare.call_count == 1


def test_update_reprocesses_when_settings_change(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output_a = PixooOutput(_config(palette_size=24), _cache(tmp_path))
    output_b = PixooOutput(_config(palette_size=8), _cache(tmp_path))

    with patch.object(output_a, "_post"), patch.object(output_b, "_post"), patch(
        "mediainfo.outputs.pixoo.prepare_led_image", side_effect=_passthrough_prepare
    ) as mock_prepare:
        output_a.update(_now_playing(), _artwork(), img_path)
        output_b.update(_now_playing(), _artwork(), img_path)

    assert mock_prepare.call_count == 2


def test_led_derivative_is_cached_as_png_alongside_original(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config(size=16), _cache(tmp_path))

    with patch.object(output, "_post"):
        output.update(_now_playing(), _artwork(), img_path)

    cached = list(tmp_path.glob("art_*.png"))
    assert len(cached) == 1
    assert Image.open(cached[0]).size == (16, 16)


def _passthrough_prepare(image, **kwargs):
    from mediainfo.led_image import prepare_led_image as real_prepare_led_image

    return real_prepare_led_image(image, **kwargs)


def test_pixoo_config_size_defaults_to_64():
    cfg = PixooConfig(enabled=True, ip="192.168.1.32")
    assert cfg.size == 64


def test_pixoo_config_preview_path_defaults_empty():
    cfg = PixooConfig(enabled=True, ip="192.168.1.32")
    assert cfg.preview_path == ""


def test_pixoo_config_led_defaults():
    cfg = PixooConfig(enabled=True, ip="192.168.1.32")
    assert cfg.crop_strategy == "automatic"
    assert cfg.palette_size == 24
    assert cfg.dithering == "none"
    assert cfg.contrast_boost == "medium"
    assert cfg.saturation_boost == "medium"
    assert cfg.dark_image_boost is True
    assert cfg.pixel_art_mode is True


def test_only_shows_album_art_for_music():
    assert PixooOutput.music_album_art_only is True


# ---------------------------------------------------------------------------
# Power/brightness scheduling (see display_schedule.py)
# ---------------------------------------------------------------------------

def test_schedule_tick_without_schedule_sends_nothing(tmp_path):
    output = PixooOutput(_config(), _cache(tmp_path))
    with patch("mediainfo.outputs.pixoo.requests.post") as mock_post:
        output.on_schedule_tick()
    mock_post.assert_not_called()


def test_schedule_tick_sends_power_and_brightness_commands(tmp_path):
    import datetime

    output = PixooOutput(
        _config(screen_off_hours="23:00-07:00", brightness_schedule=["20:00-23:00=15"]),
        _cache(tmp_path),
    )
    with patch("mediainfo.outputs.pixoo.requests.post") as mock_post:
        output._scheduler.tick(datetime.time(21, 0))

    payloads = [call.kwargs["json"] for call in mock_post.call_args_list]
    assert {"Command": "Channel/SetBrightness", "Brightness": 15} in payloads
    assert {"Command": "Channel/OnOffScreen", "OnOff": 1} in payloads

    with patch("mediainfo.outputs.pixoo.requests.post") as mock_post:
        output._scheduler.tick(datetime.time(23, 30))
    assert mock_post.call_args.kwargs["json"] == {
        "Command": "Channel/OnOffScreen", "OnOff": 0,
    }
