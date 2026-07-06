"""Configurable image-preparation pipeline for small LED matrix displays
(currently used by the Pixoo output - see mediainfo/outputs/pixoo.py).

A poster or album cover simply resized to 16x16 (or even 64x64) tends to read
as "a photo that got small" rather than deliberate pixel art: faces/logos can
land off-crop, a straight LANCZOS downscale blurs detail into mush, and PIL's
`Image.quantize()` dithers by default (Floyd-Steinberg) even when bold, clean
colour blocks were the goal. `prepare_led_image()` makes each of those steps
an explicit, independently testable choice instead of a hardcoded pipeline.

Deliberately pure/config-free (no dependency on mediainfo.config), mirroring
mediainfo/transforms.py - callers pass plain values, so this module has no
import-time coupling to any config dataclass.
"""

from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter, ImageStat

# off/low/medium/high -> PIL ImageEnhance factor. "medium" matches the
# pipeline's original hardcoded contrast boost (1.3).
_ENHANCEMENT_FACTORS = {"off": 1.0, "low": 1.15, "medium": 1.3, "high": 1.5}

# How far up from vertical-center to bias a "poster_top" crop, as a fraction
# of the available vertical slack (0.0 = flush top, 0.5 = center/no bias).
# Movie/show poster faces and title art usually sit above the true vertical
# center, but rarely at the very top edge (which risks cutting off heads).
_POSTER_TOP_BIAS = 0.15

# Dark-image boost: if the cropped image's mean luminance (0-255) is below
# this, lift brightness toward the target mean - conservatively capped so a
# genuinely near-black source (e.g. a deliberately dark album cover) isn't
# blown out.
_DARK_BOOST_THRESHOLD = 90.0
_DARK_BOOST_TARGET_MEAN = 110.0
_DARK_BOOST_MAX_FACTOR = 1.6

# In pixel-art mode, the pre-quantize downsample happens in two stages: a
# high-quality LANCZOS shrink to an intermediate size first (so the image is
# already reduced to intentional pixel clusters), then a final
# nearest-neighbour step to the exact target (crisp block edges, no blur).
# A single LANCZOS pass straight to 16x16/64x64 tends to blur small clusters
# together instead of keeping them as distinct blocks.
_PIXEL_ART_UPSCALE_FACTOR = 4

# 4x4 Bayer ordered-dither threshold matrix (0-15). PIL's quantize() only
# supports NONE or FLOYDSTEINBERG dithering natively - "ordered" dithering is
# implemented here as a small pre-quantize pixel perturbation pass.
_BAYER_4X4 = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)


def prepare_led_image(
    image: Image.Image,
    size: int = 64,
    crop_strategy: str = "automatic",
    palette_size: int = 24,
    dithering: str = "none",
    contrast_boost: str = "medium",
    saturation_boost: str = "medium",
    dark_image_boost: bool = True,
    pixel_art_mode: bool = True,
) -> Image.Image:
    """Process a full-resolution image for an LED matrix of the given size.

    Pipeline:
      0. Pass-through: an image that's already exactly size x size and
         already within the target palette is returned unchanged - this is
         what makes a hand-crafted override image (pinned via
         mediainfo/artwork_overrides.py) safe to always run through this
         function rather than needing a special case at the call site.
      1. Crop to a square, per `crop_strategy` ("center", "poster_top", or
         "automatic" - see _crop_square).
      2. Dark-image boost (if enabled) - lift brightness before the
         contrast/saturation steps so a dark poster doesn't end up mostly
         black on the LEDs.
      3. Contrast / saturation enhancement, per off/low/medium/high.
      4. In pixel-art mode: unsharp mask, then a two-stage downsample
         (LANCZOS to an intermediate size, then nearest-neighbour to the
         final size). Otherwise: a single LANCZOS pass straight to size.
      5. Dithering + palette reduction to `palette_size` colours.
    """
    image = image.convert("RGB")

    if image.size == (size, size) and image.getcolors(maxcolors=palette_size) is not None:
        return image

    image = _crop_square(image, crop_strategy)

    if dark_image_boost:
        image = _maybe_boost_dark_image(image)

    contrast_factor = _ENHANCEMENT_FACTORS.get(contrast_boost, _ENHANCEMENT_FACTORS["medium"])
    if contrast_factor != 1.0:
        image = ImageEnhance.Contrast(image).enhance(contrast_factor)

    saturation_factor = _ENHANCEMENT_FACTORS.get(saturation_boost, _ENHANCEMENT_FACTORS["medium"])
    if saturation_factor != 1.0:
        image = ImageEnhance.Color(image).enhance(saturation_factor)

    if pixel_art_mode:
        image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))
        current = image.size[0]
        intermediate = max(size, min(current, size * _PIXEL_ART_UPSCALE_FACTOR))
        image = image.resize((intermediate, intermediate), Image.Resampling.LANCZOS)
        image = image.resize((size, size), Image.Resampling.NEAREST)
    else:
        image = image.resize((size, size), Image.Resampling.LANCZOS)

    if dithering == "ordered":
        image = _apply_ordered_dither(image, palette_size)
        image = image.quantize(colors=palette_size, dither=Image.Dither.NONE).convert("RGB")
    elif dithering == "floyd_steinberg":
        image = image.quantize(colors=palette_size, dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")
    else:
        image = image.quantize(colors=palette_size, dither=Image.Dither.NONE).convert("RGB")

    return image


def _crop_square(image: Image.Image, strategy: str) -> Image.Image:
    w, h = image.size
    s = min(w, h)
    left = (w - s) // 2

    biased = strategy == "poster_top" or (strategy == "automatic" and h > w)
    top = int((h - s) * _POSTER_TOP_BIAS) if biased else (h - s) // 2

    return image.crop((left, top, left + s, top + s))


def _maybe_boost_dark_image(image: Image.Image) -> Image.Image:
    mean = ImageStat.Stat(image.convert("L")).mean[0]
    if mean <= 0 or mean >= _DARK_BOOST_THRESHOLD:
        return image
    factor = min(_DARK_BOOST_TARGET_MEAN / mean, _DARK_BOOST_MAX_FACTOR)
    return ImageEnhance.Brightness(image).enhance(factor)


def _apply_ordered_dither(image: Image.Image, palette_size: int) -> Image.Image:
    w, h = image.size
    strength = max(1, 255 // max(palette_size, 1))
    for y in range(h):
        row = _BAYER_4X4[y % 4]
        for x in range(w):
            offset = (row[x % 4] / 16 - 0.5) * strength
            r, g, b = image.getpixel((x, y))  # type: ignore[misc]
            image.putpixel((x, y), (_clamp8(r + offset), _clamp8(g + offset), _clamp8(b + offset)))
    return image


def _clamp8(value: float) -> int:
    return max(0, min(255, int(round(value))))
