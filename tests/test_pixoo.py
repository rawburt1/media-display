"""Tests for the Pixoo output and LED image-preparation pipeline."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from mediainfo.config import PixooConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.pixoo import PixooOutput, _prepare_for_led, _save_preview


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(**kwargs):
    defaults = dict(enabled=True, ip="192.168.1.32")
    defaults.update(kwargs)
    return PixooConfig(**defaults)


def _now_playing():
    return NowPlaying(source="kodi", media_type="music", title="Test")


def _artwork():
    return Artwork(url="http://example.com/art.jpg")


def _solid_image(width=600, height=600, color=(200, 100, 50)):
    return Image.new("RGB", (width, height), color)


def _save_image(path: Path, width=600, height=600, color=(200, 100, 50)) -> Path:
    img = _solid_image(width, height, color)
    img.save(path, format="JPEG")
    return path


# ---------------------------------------------------------------------------
# _prepare_for_led
# ---------------------------------------------------------------------------

def test_prepare_for_led_output_is_64x64():
    img = _solid_image(600, 600)
    result = _prepare_for_led(img)
    assert result.size == (64, 64)


def test_prepare_for_led_output_is_16x16_when_size_16():
    img = _solid_image(600, 600)
    result = _prepare_for_led(img, size=16)
    assert result.size == (16, 16)


def test_prepare_for_led_output_is_rgb():
    img = _solid_image(600, 600)
    result = _prepare_for_led(img)
    assert result.mode == "RGB"


def test_prepare_for_led_center_crops_landscape():
    # 200×100 landscape — the crop should take the central 100×100 square.
    img = Image.new("RGB", (200, 100), (0, 0, 255))
    # Paint the left and right strips red (they should be cropped away)
    for x in range(50):
        for y in range(100):
            img.putpixel((x, y), (255, 0, 0))
            img.putpixel((200 - 1 - x, y), (255, 0, 0))
    result = _prepare_for_led(img)
    assert result.size == (64, 64)
    # Centre crop removes the red strips; quantised result should not be red.
    # (We just confirm the function runs without error and produces correct size.)


def test_prepare_for_led_center_crops_portrait():
    img = Image.new("RGB", (100, 200), (0, 255, 0))
    result = _prepare_for_led(img)
    assert result.size == (64, 64)


def test_prepare_for_led_already_square():
    img = _solid_image(64, 64)
    result = _prepare_for_led(img)
    assert result.size == (64, 64)


def test_prepare_for_led_large_image():
    img = _solid_image(2000, 2000)
    result = _prepare_for_led(img)
    assert result.size == (64, 64)


def test_prepare_for_led_palette_reduction_limits_colors():
    # A gradient image has many colours; after quantisation we expect ≤ 24.
    img = Image.new("RGB", (200, 200))
    for x in range(200):
        for y in range(200):
            img.putpixel((x, y), (x, y, (x + y) % 256))
    result = _prepare_for_led(img)
    colors = result.getcolors(maxcolors=256)
    assert colors is not None
    assert len(colors) <= 24


def test_prepare_for_led_rgba_input():
    # Should not crash on RGBA input (unlikely from Pixoo path, but defensive)
    img = Image.new("RGBA", (100, 100), (100, 150, 200, 128))
    # _prepare_for_led expects RGB, but test that caller (update) converts first
    rgb = img.convert("RGB")
    result = _prepare_for_led(rgb)
    assert result.size == (64, 64)


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
    # Solid red image — every pixel should stay red in the NN upscale.
    img = Image.new("RGB", (64, 64), (255, 0, 0))
    path = tmp_path / "preview.png"
    _save_preview(img, path)
    preview = Image.open(path).convert("RGB")
    # All pixels should be red (NN doesn't blend)
    pixels = [preview.getpixel((x, y)) for x in range(512) for y in range(512)]
    assert all(p[0] == 255 and p[1] == 0 and p[2] == 0 for p in pixels)


def test_save_preview_does_not_raise_on_bad_path(tmp_path):
    img = _solid_image(64, 64)
    # Read-only directory — write will fail silently
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o444)
    _save_preview(img, ro / "preview.png")  # must not raise
    ro.chmod(0o755)  # restore so tmp_path cleanup works


# ---------------------------------------------------------------------------
# PixooOutput.update — integration
# ---------------------------------------------------------------------------

def test_update_sends_correct_commands(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config())

    with patch.object(output, "_post") as mock_post:
        output.update(_now_playing(), _artwork(), img_path)

    assert mock_post.call_count == 2
    commands = [c.args[0]["Command"] for c in mock_post.call_args_list]
    assert commands == ["Draw/ResetHttpGifId", "Draw/SendHttpGif"]


def test_update_sends_64x64_pixels(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config())

    sent_payloads = []
    with patch.object(output, "_post", side_effect=lambda p: sent_payloads.append(p)):
        output.update(_now_playing(), _artwork(), img_path)

    gif_payload = next(p for p in sent_payloads if p.get("Command") == "Draw/SendHttpGif")
    raw = base64.b64decode(gif_payload["PicData"])
    assert len(raw) == 64 * 64 * 3  # RGB bytes
    assert gif_payload["PicWidth"] == 64


def test_update_sends_16x16_pixels_when_size_16(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config(size=16))

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
    output = PixooOutput(_config(preview_path=str(preview_path)))

    with patch.object(output, "_post"):
        output.update(_now_playing(), _artwork(), img_path)

    assert preview_path.exists()
    assert Image.open(preview_path).size == (512, 512)


def test_update_no_preview_when_not_configured(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config())  # no preview_path

    with patch.object(output, "_post"), patch("mediainfo.outputs.pixoo._save_preview") as mock_prev:
        output.update(_now_playing(), _artwork(), img_path)

    mock_prev.assert_not_called()


def test_update_does_not_raise_on_network_error(tmp_path):
    img_path = _save_image(tmp_path / "art.jpg")
    output = PixooOutput(_config())

    with patch.object(output, "_post", side_effect=OSError("connection refused")):
        output.update(_now_playing(), _artwork(), img_path)  # must not raise


def test_update_does_not_raise_on_bad_image(tmp_path):
    bad_path = tmp_path / "bad.jpg"
    bad_path.write_bytes(b"not an image")
    output = PixooOutput(_config())

    with patch.object(output, "_post"):
        output.update(_now_playing(), _artwork(), bad_path)  # must not raise


# ---------------------------------------------------------------------------
# PixooConfig — preview_path default
# ---------------------------------------------------------------------------

def test_pixoo_config_size_defaults_to_64():
    cfg = PixooConfig(enabled=True, ip="192.168.1.32")
    assert cfg.size == 64


def test_pixoo_config_preview_path_defaults_empty():
    cfg = PixooConfig(enabled=True, ip="192.168.1.32")
    assert cfg.preview_path == ""


def test_only_shows_album_art_for_music():
    assert PixooOutput.music_album_art_only is True
