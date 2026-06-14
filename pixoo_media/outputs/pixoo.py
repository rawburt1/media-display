"""Pixoo64 output: pushes artwork to a Divoom Pixoo64 over its local HTTP API."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import requests
from PIL import Image, ImageOps

from pixoo_media.config import PixooConfig
from pixoo_media.models import Artwork, NowPlaying
from pixoo_media.outputs.base import Output

logger = logging.getLogger(__name__)

_SIZE = 64


class PixooOutput(Output):
    def __init__(self, config: PixooConfig):
        self.config = config
        self._url = f"http://{config.ip}/post"

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        try:
            image = Image.open(image_path).convert("RGB")
            image = ImageOps.fit(image, (_SIZE, _SIZE))
            pixel_data = base64.b64encode(image.tobytes()).decode("ascii")

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
