"""Pixoo64 output: pushes artwork to a Divoom Pixoo64 over its local HTTP API."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import requests
from PIL import Image, ImageEnhance, ImageFilter

from pixoo_media.config import PixooConfig
from pixoo_media.models import Artwork, NowPlaying
from pixoo_media.outputs.base import Output
from pixoo_media.transforms import parse_pipeline

logger = logging.getLogger(__name__)

_SIZE = 64
_PALETTE_COLORS = 24


class PixooOutput(Output):
    def __init__(self, config: PixooConfig):
        self.config = config
        self._url = f"http://{config.ip}/post"
        self.transform_pipeline = parse_pipeline(config.transforms)

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        try:
            image = Image.open(image_path).convert("RGB")
            image = _prepare_for_led(image)
            pixel_data = base64.b64encode(image.tobytes()).decode("ascii")

            if self.config.preview_path:
                _save_preview(image, Path(self.config.preview_path))

            # Reset the gif id before each send so repeated single-frame
            # updates never run into Pixoo's PicId exhaustion error.
            self._post({"Command": "Draw/ResetHttpGifId"})
            self._post(
                {
                    "Command": "Draw/SendHttpGif",
                    "PicNum": 1,
                    "PicWidth": _SIZE,
                    "PicOffset": 0,
                    "PicID": 1,
                    "PicSpeed": 1000,
                    "PicData": pixel_data,
                }
            )
        except Exception:
            logger.exception("Failed to send image to Pixoo64")

    def _post(self, payload: dict) -> None:
        response = requests.post(self._url, json=payload, timeout=5)
        response.raise_for_status()


def _prepare_for_led(image: Image.Image) -> Image.Image:
    """Process a full-resolution image for a 64×64 LED matrix.

    Pipeline:
      1. Center-crop to square so the subject fills the frame.
      2. Boost contrast before downscaling (makes colours pop at low res).
      3. Unsharp mask to preserve edge sharpness through the downscale.
      4. Downsample to 64×64 with LANCZOS.
      5. Quantize to ~24 colours so the LED shows bold, clean blocks.
    """
    # 1. Center-crop to square
    w, h = image.size
    s = min(w, h)
    left = (w - s) // 2
    top = (h - s) // 2
    image = image.crop((left, top, left + s, top + s))

    # 2. Contrast boost
    image = ImageEnhance.Contrast(image).enhance(1.3)

    # 3. Unsharp mask — radius is relative to the source size, so use a
    #    moderate value that sharpens without adding noise.
    image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))

    # 4. Downsample
    image = image.resize((_SIZE, _SIZE), Image.LANCZOS)

    # 5. Palette reduction → bold colour blocks
    image = image.quantize(colors=_PALETTE_COLORS).convert("RGB")

    return image


def _save_preview(image: Image.Image, path: Path) -> None:
    """Save a 512×512 nearest-neighbour upscale — shows exactly what the LED sees."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        image.resize((512, 512), Image.NEAREST).save(path, format="PNG")
    except Exception:
        logger.warning("Could not save Pixoo preview to %s", path)
