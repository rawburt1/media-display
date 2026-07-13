"""Pixoo output: pushes artwork to a Divoom Pixoo over its local HTTP API.

Supports any Pixoo display size — configure `size: 64` for the Pixoo64
(default) or `size: 16` for the Pixoo 16×16 Pixel Art LED Frame.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path

import requests
from PIL import Image

from mediainfo.cache import ImageCache
from mediainfo.config import PixooConfig
from mediainfo.display_schedule import DisplaySchedule, ScheduledDisplay
from mediainfo.imaging.led_image import prepare_led_image
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output
from mediainfo.imaging.text_removal import maybe_remove_text
from mediainfo.imaging.transforms import parse_pipeline

logger = logging.getLogger(__name__)

# Bump when mediainfo.imaging.led_image's pipeline logic changes in a way that
# should invalidate previously cached derivatives, even though none of the
# user-facing settings below changed.
_LED_PIPELINE_VERSION = 1


class PixooOutput(Output):
    name = "pixoo"
    config_class = PixooConfig
    # The LED matrix is too small/low-fidelity to make an unrelated artist
    # bio photo (Wikipedia, Last.fm) worth showing — only show album art.
    music_album_art_only = True

    def __init__(self, config: PixooConfig, cache: ImageCache):
        self.config = config
        self.cache = cache
        self._url = f"http://{config.ip}/post"
        self.transform_pipeline = parse_pipeline(config.transforms)
        self._scheduler = ScheduledDisplay(
            DisplaySchedule(config.screen_off_hours, config.brightness_schedule),
            set_power=self._set_power,
            set_brightness=self._set_brightness,
            label=f"Pixoo {config.ip}",
        )

    def on_schedule_tick(self) -> None:
        self._scheduler.tick()

    def _set_power(self, on: bool) -> None:
        self._post({"Command": "Channel/OnOffScreen", "OnOff": 1 if on else 0})

    def _set_brightness(self, level: int) -> None:
        self._post({"Command": "Channel/SetBrightness", "Brightness": level})

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        # Deliberately no try/except here - letting connection errors
        # propagate lets the orchestrator's _call_output() record them for
        # health/alerting (see orchestrator.py:_call_output). Swallowing
        # them here used to mean a Pixoo that dropped off the network was
        # silently reported as healthy.
        size = self.config.size
        led_path = self.cache.get_derived_path(
            image_path, self._led_cache_key(), self._build_led_image
        )
        image = Image.open(led_path).convert("RGB")
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

    def on_idle(self) -> None:
        # Same protocol as update(), sent with an all-zero (black) buffer -
        # there's no dedicated "clear" command in the Pixoo HTTP API. This
        # is what keeps the display from getting stuck on stale artwork
        # when e.g. every candidate image gets filtered out for this
        # output (see orchestrator_artwork.py's show_image_for_output).
        size = self.config.size
        blank = base64.b64encode(bytes(size * size * 3)).decode("ascii")
        self._post({"Command": "Draw/ResetHttpGifId"})
        self._post(
            {
                "Command": "Draw/SendHttpGif",
                "PicNum": 1,
                "PicWidth": size,
                "PicOffset": 0,
                "PicID": 1,
                "PicSpeed": 1000,
                "PicData": blank,
            }
        )

    def _build_led_image(self, img: Image.Image) -> tuple:
        """The get_derived_path build callback: optional text removal, then
        the LED-preparation pipeline. Returns (image, decision-record) so
        the text-removal decision (if the stage ran) is persisted as a
        `{cache_key}.json` sidecar next to the cached derivative.
        """
        img, decision = maybe_remove_text(
            img,
            target_size=self.config.size,
            enabled=self.config.text_detection_enabled,
            model_path=self.config.text_detection_model_path,
            remove_small_text=self.config.remove_small_text,
            preserve_large_logos=self.config.preserve_large_logos,
            removal_method=self.config.text_removal_method,
            max_logo_area_percent=self.config.max_logo_area_percent,
            crop_strategy=self.config.crop_strategy,
        )
        final = prepare_led_image(
            img,
            size=self.config.size,
            crop_strategy=self.config.crop_strategy,
            palette_size=self.config.palette_size,
            dithering=self.config.dithering,
            contrast_boost=self.config.contrast_boost,
            saturation_boost=self.config.saturation_boost,
            dark_image_boost=self.config.dark_image_boost,
            pixel_art_mode=self.config.pixel_art_mode,
        )
        return final, decision

    def _led_cache_key(self) -> str:
        """Stable hash of every setting that affects _build_led_image's
        output, plus _LED_PIPELINE_VERSION - so changing a setting (or the
        pipeline's own logic) invalidates the cached derivative, and
        unrelated instances/settings never collide on the same file.
        """
        spec = {
            "version": _LED_PIPELINE_VERSION,
            "size": self.config.size,
            "crop_strategy": self.config.crop_strategy,
            "palette_size": self.config.palette_size,
            "dithering": self.config.dithering,
            "contrast_boost": self.config.contrast_boost,
            "saturation_boost": self.config.saturation_boost,
            "dark_image_boost": self.config.dark_image_boost,
            "pixel_art_mode": self.config.pixel_art_mode,
            "text_detection_enabled": self.config.text_detection_enabled,
            "text_detection_model_path": self.config.text_detection_model_path,
            "remove_small_text": self.config.remove_small_text,
            "preserve_large_logos": self.config.preserve_large_logos,
            "text_removal_method": self.config.text_removal_method,
            "max_logo_area_percent": self.config.max_logo_area_percent,
        }
        return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]

    def _post(self, payload: dict) -> None:
        response = requests.post(self._url, json=payload, timeout=5)
        response.raise_for_status()


def _save_preview(image: Image.Image, path: Path) -> None:
    """Save a 512×512 nearest-neighbour upscale — shows exactly what the LED sees."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        image.resize((512, 512), Image.Resampling.NEAREST).save(path, format="PNG")
    except Exception:
        logger.warning("Could not save Pixoo preview to %s", path)
