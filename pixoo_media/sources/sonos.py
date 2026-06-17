"""Sonos "now playing" source using the soco library."""

from __future__ import annotations

import logging
from typing import Optional

from soco import SoCo

from pixoo_media.config import SonosConfig
from pixoo_media.models import Artwork, NowPlaying
from pixoo_media.sources.base import MediaSource

logger = logging.getLogger(__name__)


class SonosSource(MediaSource):
    name = "sonos"

    def __init__(self, config: SonosConfig):
        self.config = config
        # Seed device used to fetch the full zone topology. All groups
        # (and their coordinators) are discovered from this one entry point,
        # so music playing on any Sonos zone is detected.
        self._seed = SoCo(config.speaker_ip)

    def get_now_playing(self) -> Optional[NowPlaying]:
        try:
            seen: set[str] = set()
            for group in self._seed.all_groups:
                coordinator = group.coordinator
                if coordinator.ip_address in seen:
                    continue
                seen.add(coordinator.ip_address)
                if self._is_blacklisted(coordinator):
                    continue
                try:
                    result = self._check(coordinator)
                except Exception:
                    logger.debug("Skipping %s: unsupported", coordinator.ip_address)
                    continue
                if result is not None:
                    return result
            return None
        except Exception:
            logger.exception("Sonos source error")
            return None

    def _is_blacklisted(self, device) -> bool:
        if not self.config.blacklist:
            return False
        return (
            device.ip_address in self.config.blacklist
            or device.player_name in self.config.blacklist
        )

    def _check(self, device: SoCo) -> Optional[NowPlaying]:
        transport = device.get_current_transport_info()
        # Accept TRANSITIONING so we detect playback as soon as it starts,
        # before Sonos settles into PLAYING.
        if transport.get("current_transport_state") not in ("PLAYING", "TRANSITIONING"):
            return None

        track = device.get_current_track_info()
        title = track.get("title", "")
        if not title:
            return None

        image_url = track.get("album_art", "")
        if image_url and not image_url.startswith("http"):
            image_url = f"http://{device.ip_address}:1400{image_url}"

        images = []
        if image_url:
            images.append(Artwork(url=image_url, label="Album art (Sonos)"))

        return NowPlaying(
            source=self.name,
            media_type="music",
            title=title,
            subtitle=track.get("artist", ""),
            album=track.get("album", ""),
            images=images,
        )
