"""Pixoo output: pushes artwork to a Divoom Pixoo over its local HTTP API.

Supports any Pixoo display size — configure `size: 64` for the Pixoo64
(default) or `size: 16` for the Pixoo 16×16 Pixel Art LED Frame.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import requests
from PIL import Image, ImageEnhance, ImageFilter

from mediainfo.config import PixooConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output
from mediainfo.transforms import parse_pipeline

logger = logging.getLogger(__name__)

_PALETTE_COLORS = 24


class PixooOutput(Output):
    # The LED matrix is too small/low-fidelity to make an unrelated artist
    # bio photo (Wikipedia, Last.fm) worth showing — only show album art.
    music_album_art_only = True

    def __init__(self, config: PixooConfig):
        self.config = config
        self._url = f"http://{config.ip}/post"
        self.transform_pipeline = parse_pipeline(config.transforms)

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        size = self.config.size
        try:
            image = Image.open(image_path).convert("RGB")
            image = _prepare_for_led(image, size)
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
                    "PicWidth": size,
                    "PicOffset": 0,
                    "PicID": 1,
                    "PicSpeed": 1000,
                    "PicData": pixel_data,
                }
            )
        except Exception:
            logger.exception("Failed to send image to Pixoo at %s", self.config.ip)

    def _post(self, payload: dict) -> None:
        response = requests.post(self._url, json=payload, timeout=5)
        response.raise_for_status()


def _prepare_for_led(image: Image.Image, size: int = 64) -> Image.Image:
    """Process a full-resolution image for an LED matrix of the given size.

    Pipeline:
      1. Center-crop to square so the subject fills the frame.
      2. Boost contrast before downscaling (makes colours pop at low res).
      3. Unsharp mask to preserve edge sharpness through the downscale.
      4. Downsample to size×size with LANCZOS.
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
    image = image.resize((size, size), Image.Resampling.LANCZOS)

    # 5. Palette reduction → bold colour blocks
    image = image.quantize(colors=_PALETTE_COLORS).convert("RGB")

    return image


def _save_preview(image: Image.Image, path: Path) -> None:
    """Save a 512×512 nearest-neighbour upscale — shows exactly what the LED sees."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        image.resize((512, 512), Image.Resampling.NEAREST).save(path, format="PNG")
    except Exception:
        logger.warning("Could not save Pixoo preview to %s", path)
