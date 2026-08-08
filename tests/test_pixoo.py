"""Tests for the Pixoo output: HTTP payload construction, scheduling, and
disk-caching of the LED-prepared derivative (see mediainfo/led_image.py for
the pipeline itself, tested in test_led_image.py)."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

import pytest
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
# Optional dependency: opencv-python-headless/numpy (N3 - see
# docs/architecture-usability-review-2026-07.md) are only needed by the
# text-detection stage (mediainfo/text_removal.py's _import_cv2(), lazy and
# already gated behind text_detection_enabled/model_path) - base Pixoo
# output must work fine without either installed. Locks in behavior that
# was already correct (verified by hand before N3's M0/M2), guarding
# against a future eager `import cv2`/`import numpy` creeping into
# pixoo.py or text_removal.py's module level.
#
# A real subprocess, not an in-process sys.modules/builtins.__import__
# patch: by the time this test file's own top-level `from
# mediainfo.outputs.pixoo import PixooOutput` has run, both
# mediainfo.outputs.pixoo and mediainfo.imaging.text_removal are already cached in
# sys.modules, so patching __import__ afterward wouldn't force a real
# re-import - only a fresh interpreter that's never imported them proves
# the module-level import path itself doesn't need cv2/numpy.
# ---------------------------------------------------------------------------


def test_pixoo_output_importable_and_constructible_without_opencv_or_numpy():
    import subprocess
    import sys

    script = (
        "import sys, importlib.abc, importlib.machinery\n"
        "class _Blocker(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path, target=None):\n"
        "        if name in ('cv2', 'numpy'):\n"
        "            raise ImportError(f'simulated missing {name}')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Blocker())\n"
        "from mediainfo.outputs.pixoo import PixooOutput\n"
        "from mediainfo.config import PixooConfig\n"
        "from mediainfo.cache import ImageCache\n"
        "import tempfile\n"
        "cfg = PixooConfig(enabled=True, ip='192.168.1.32', text_detection_enabled=False)\n"
        "out = PixooOutput(cfg, ImageCache(tempfile.mkdtemp()))\n"
        "assert out is not None\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


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

    assert mock_post.call_count == 3
    commands = [c.args[0]["Command"] for c in mock_post.call_args_list]
    assert commands == ["Channel/SetIndex", "Draw/ResetHttpGifId", "Draw/SendHttpGif"]


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


def test_update_forces_custom_channel_before_drawing(tmp_path):
    # A Pixoo accepts Draw/SendHttpGif (200, error_code 0) no matter which
    # channel it's currently showing, but only renders it while on the
    # custom channel - see _CUSTOM_CHANNEL_INDEX. Without this, a device
    # left on Clock/Cloud/Visualizer (its own remote, the Divoom app, or
    # its power-on default) silently never displays what's pushed.
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config(), _cache(tmp_path))

    with patch.object(output, "_post") as mock_post:
        output.update(_now_playing(), _artwork(), img_path)

    assert mock_post.call_args_list[0].args[0] == {
        "Command": "Channel/SetIndex",
        "SelectIndex": 3,
    }


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


# ---------------------------------------------------------------------------
# on_idle
# ---------------------------------------------------------------------------


def test_on_idle_sends_correct_commands(tmp_path):
    output = PixooOutput(_config(), _cache(tmp_path))

    with patch.object(output, "_post") as mock_post:
        output.on_idle()

    assert mock_post.call_count == 3
    commands = [c.args[0]["Command"] for c in mock_post.call_args_list]
    assert commands == ["Channel/SetIndex", "Draw/ResetHttpGifId", "Draw/SendHttpGif"]


def test_on_idle_sends_an_all_black_frame(tmp_path):
    output = PixooOutput(_config(), _cache(tmp_path))

    sent_payloads = []
    with patch.object(output, "_post", side_effect=lambda p: sent_payloads.append(p)):
        output.on_idle()

    gif_payload = next(p for p in sent_payloads if p.get("Command") == "Draw/SendHttpGif")
    raw = base64.b64decode(gif_payload["PicData"])
    assert len(raw) == 64 * 64 * 3
    assert raw == bytes(64 * 64 * 3)
    assert gif_payload["PicWidth"] == 64


def test_on_idle_sends_correctly_sized_frame_for_size_16(tmp_path):
    output = PixooOutput(_config(size=16), _cache(tmp_path))

    sent_payloads = []
    with patch.object(output, "_post", side_effect=lambda p: sent_payloads.append(p)):
        output.on_idle()

    gif_payload = next(p for p in sent_payloads if p.get("Command") == "Draw/SendHttpGif")
    raw = base64.b64decode(gif_payload["PicData"])
    assert len(raw) == 16 * 16 * 3
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


def test_update_raises_on_network_error(tmp_path):
    # So the orchestrator's _call_output() can record it for health/
    # alerting - see orchestrator.py:_call_output.
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config(), _cache(tmp_path))

    with patch.object(output, "_post", side_effect=OSError("connection refused")):
        with pytest.raises(OSError):
            output.update(_now_playing(), _artwork(), img_path)


def test_update_raises_on_bad_image(tmp_path):
    bad_path = tmp_path / "bad.jpg"
    bad_path.write_bytes(b"not an image")
    output = PixooOutput(_config(), _cache(tmp_path))

    with patch.object(output, "_post"):
        with pytest.raises(Exception):
            output.update(_now_playing(), _artwork(), bad_path)


# ---------------------------------------------------------------------------
# Disk caching of the LED-prepared derivative
# ---------------------------------------------------------------------------


def test_update_only_prepares_image_once_for_repeated_calls(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config(), _cache(tmp_path))

    with (
        patch.object(output, "_post"),
        patch(
            "mediainfo.outputs.pixoo.prepare_led_image", side_effect=_passthrough_prepare
        ) as mock_prepare,
    ):
        output.update(_now_playing(), _artwork(), img_path)
        output.update(_now_playing(), _artwork(), img_path)

    assert mock_prepare.call_count == 1


def test_update_reprocesses_when_settings_change(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output_a = PixooOutput(_config(palette_size=24), _cache(tmp_path))
    output_b = PixooOutput(_config(palette_size=8), _cache(tmp_path))

    with (
        patch.object(output_a, "_post"),
        patch.object(output_b, "_post"),
        patch(
            "mediainfo.outputs.pixoo.prepare_led_image", side_effect=_passthrough_prepare
        ) as mock_prepare,
    ):
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
    from mediainfo.imaging.led_image import prepare_led_image as real_prepare_led_image

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


def test_pixoo_config_text_detection_defaults():
    cfg = PixooConfig(enabled=True, ip="192.168.1.32")
    assert cfg.text_detection_enabled is False
    assert cfg.text_detection_model_path == ""
    assert cfg.remove_small_text is True
    assert cfg.preserve_large_logos is True
    assert cfg.text_removal_method == "inpaint"
    assert cfg.max_logo_area_percent == 25.0


def test_text_detection_disabled_by_default_does_not_call_detector(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config(), _cache(tmp_path))

    with (
        patch.object(output, "_post"),
        patch("mediainfo.imaging.text_removal.detect_text_regions") as mock_detect,
    ):
        output.update(_now_playing(), _artwork(), img_path)

    mock_detect.assert_not_called()


def test_text_detection_settings_change_the_led_cache_key(tmp_path):
    output_a = PixooOutput(_config(text_detection_enabled=False), _cache(tmp_path))
    output_b = PixooOutput(
        _config(text_detection_enabled=True, text_detection_model_path="/x.pb"), _cache(tmp_path)
    )

    assert output_a._led_cache_key() != output_b._led_cache_key()


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
        "Command": "Channel/OnOffScreen",
        "OnOff": 0,
    }


# ---------------------------------------------------------------------------
# PixooConfig validation (pydantic dataclass rollout - see
# mediainfo/config/outputs.py)
# ---------------------------------------------------------------------------


def test_config_unknown_field_raises_validation_error():
    import pytest

    with pytest.raises(ValueError, match="no_such_field"):
        PixooConfig(enabled=True, no_such_field="x")


def test_config_coerces_string_int_size():
    cfg = PixooConfig(enabled=True, size="16")
    assert cfg.size == 16
    assert isinstance(cfg.size, int)


def test_config_transforms_default_is_independent_per_instance():
    cfg1 = PixooConfig()
    cfg1.transforms.append({"grayscale": True})
    cfg2 = PixooConfig()
    assert cfg2.transforms == []
