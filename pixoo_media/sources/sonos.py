"""Sonos "now playing" source using the soco library."""

from __future__ import annotations

import logging
from typing import Optional

from soco import SoCo

from pixoo_media.config import SonosConfig
from pixoo_media.models import Artwork, NowPlaying
from pixoo_media.sources.base import MediaSource

logger = logging.getLogger(__name__)

_ACTIVE_STATES = {"PLAYING", "PAUSED_PLAYBACK"}


class SonosSource(MediaSource):
    name = "sonos"

    def __init__(self, config: SonosConfig):
        self.config = config
        self._device = SoCo(config.speaker_ip)

    def get_now_playing(self) -> Optional[NowPlaying]:
        try:
            transport = self._device.get_current_transport_info()
            if transport.get("current_transport_state") not in _ACTIVE_STATES:
                return None

            track = self._device.get_current_track_info()
            title = track.get("title", "")
            if not title:
                return None

            image_url = track.get("album_art", "")
            if image_url and not image_url.startswith("http"):
                image_url = f"http://{self.config.speaker_ip}:1400{image_url}"

            images = []
            if image_url:
                images.append(Artwork(url=image_url, label="Album art (Sonos)"))

            return NowPlaying(
                source=self.name,
                media_type="music",
                title=title,
                subtitle=track.get("artist", ""),
                images=images,
            )
        except Exception:
            logger.exception("Sonos source error")
            return None
