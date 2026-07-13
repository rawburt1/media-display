"""Tests for mediainfo/led_image.py's configurable LED-preparation pipeline."""

from __future__ import annotations

from PIL import Image

from mediainfo.imaging.led_image import _crop_square, prepare_led_image


def _solid_image(width=600, height=600, color=(200, 100, 50)):
    return Image.new("RGB", (width, height), color)


def _gradient_image(size=200):
    img = Image.new("RGB", (size, size))
    for x in range(size):
        for y in range(size):
            img.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
    return img


# ---------------------------------------------------------------------------
# Output size / mode
# ---------------------------------------------------------------------------


def test_output_is_64x64_by_default():
    result = prepare_led_image(_solid_image())
    assert result.size == (64, 64)
    assert result.mode == "RGB"


def test_output_is_16x16_when_size_16():
    result = prepare_led_image(_solid_image(), size=16)
    assert result.size == (16, 16)


def test_rgba_input_is_handled_safely():
    img = Image.new("RGBA", (100, 100), (100, 150, 200, 128))
    result = prepare_led_image(img, size=16)
    assert result.size == (16, 16)
    assert result.mode == "RGB"


def test_transparent_source_is_not_flattened_to_black():
    # A subject on an otherwise fully transparent background (RGB zeroed
    # under alpha=0, as many encoders do) must composite onto white, not
    # collapse into a mostly-black result - see flatten_transparency.
    img = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    for x in range(100, 200):
        for y in range(100, 200):
            img.putpixel((x, y), (200, 30, 30, 255))

    result = prepare_led_image(img, size=16, dark_image_boost=False, crop_strategy="center")

    colors = result.getcolors(maxcolors=256)
    mean_brightness = sum(sum(c) * count for count, c in colors) / (16 * 16 * 3)
    assert mean_brightness > 60  # would be near-black (~14) without the fix


def test_portrait_and_landscape_sources_both_produce_correct_size():
    assert prepare_led_image(Image.new("RGB", (100, 200), (0, 255, 0)), size=16).size == (16, 16)
    assert prepare_led_image(Image.new("RGB", (200, 100), (0, 0, 255)), size=16).size == (16, 16)


def test_pixel_art_mode_on_and_off_both_produce_correct_size():
    img = _gradient_image()
    assert prepare_led_image(img, size=16, pixel_art_mode=True).size == (16, 16)
    assert prepare_led_image(img, size=16, pixel_art_mode=False).size == (16, 16)


# ---------------------------------------------------------------------------
# Pass-through (already-prepared / hand-crafted override art)
# ---------------------------------------------------------------------------


def test_already_correct_size_and_palette_passes_through_unchanged():
    img = Image.new("RGB", (16, 16), (10, 20, 30))
    result = prepare_led_image(img, size=16, palette_size=24)
    assert result.size == (16, 16)
    assert list(result.get_flattened_data()) == list(img.get_flattened_data())


def test_correct_size_but_too_many_colors_is_still_processed():
    img = _gradient_image(16)
    result = prepare_led_image(img, size=16, palette_size=8)
    colors = result.getcolors(maxcolors=256)
    assert colors is not None
    assert len(colors) <= 8


# ---------------------------------------------------------------------------
# Crop strategies
# ---------------------------------------------------------------------------


def test_center_crop_is_vertically_centered_for_portrait():
    img = Image.new("RGB", (100, 200))
    result = _crop_square(img, "center")
    assert result.size == (100, 100)
    # (h - s) // 2 == 50
    # crop() doesn't expose its box directly, so re-derive via a marker pixel
    marker = Image.new("RGB", (100, 200))
    marker.putpixel((0, 50), (255, 0, 0))
    cropped = _crop_square(marker, "center")
    assert cropped.getpixel((0, 0)) == (255, 0, 0)


def test_poster_top_crop_is_biased_above_center_for_portrait():
    marker = Image.new("RGB", (100, 200))
    # (h - s) * 0.15 == 15, vs center's 50 - the poster_top crop should
    # start higher up (closer to y=15 than y=50).
    marker.putpixel((0, 15), (255, 0, 0))
    cropped = _crop_square(marker, "poster_top")
    assert cropped.getpixel((0, 0)) == (255, 0, 0)


def test_poster_top_is_a_no_op_for_landscape():
    center = _crop_square(Image.new("RGB", (200, 100), (1, 2, 3)), "center")
    top = _crop_square(Image.new("RGB", (200, 100), (1, 2, 3)), "poster_top")
    assert center.size == top.size == (100, 100)


def test_automatic_matches_poster_top_for_portrait():
    marker = Image.new("RGB", (100, 200))
    marker.putpixel((0, 15), (255, 0, 0))
    assert _crop_square(marker, "automatic").getpixel((0, 0)) == (255, 0, 0)


def test_automatic_matches_center_for_landscape_and_square():
    landscape = Image.new("RGB", (200, 100), (1, 2, 3))
    assert list(_crop_square(landscape, "automatic").get_flattened_data()) == list(
        _crop_square(landscape, "center").get_flattened_data()
    )
    square = Image.new("RGB", (100, 100), (1, 2, 3))
    assert list(_crop_square(square, "automatic").get_flattened_data()) == list(
        _crop_square(square, "center").get_flattened_data()
    )


# ---------------------------------------------------------------------------
# Palette / dithering
# ---------------------------------------------------------------------------


def test_palette_size_is_honored_for_all_dithering_modes():
    img = _gradient_image()
    for dithering in ("none", "ordered", "floyd_steinberg"):
        for palette_size in (8, 16, 24, 32):
            result = prepare_led_image(img, size=32, palette_size=palette_size, dithering=dithering)
            colors = result.getcolors(maxcolors=256)
            assert colors is not None
            assert len(colors) <= palette_size, (dithering, palette_size)


def test_none_dithering_does_not_raise_and_returns_correct_size():
    result = prepare_led_image(_gradient_image(), dithering="none", size=16)
    assert result.size == (16, 16)


# ---------------------------------------------------------------------------
# Dark-image boost
# ---------------------------------------------------------------------------


def test_dark_image_boost_raises_mean_brightness():
    dark = Image.new("RGB", (200, 200), (10, 10, 10))
    boosted = prepare_led_image(
        dark, size=32, dark_image_boost=True, contrast_boost="off", saturation_boost="off"
    )
    unboosted = prepare_led_image(
        dark, size=32, dark_image_boost=False, contrast_boost="off", saturation_boost="off"
    )
    boosted_mean = sum(sum(p) for p in boosted.get_flattened_data()) / (32 * 32 * 3)
    unboosted_mean = sum(sum(p) for p in unboosted.get_flattened_data()) / (32 * 32 * 3)
    assert boosted_mean > unboosted_mean


def test_dark_image_does_not_become_entirely_black():
    dark = Image.new("RGB", (200, 200), (5, 5, 5))
    result = prepare_led_image(dark, size=16, dark_image_boost=True)
    assert any(p != (0, 0, 0) for p in result.get_flattened_data())
