"""Sonos "now playing" source using the soco library."""

from __future__ import annotations

import logging
from typing import Optional

from soco import SoCo

from mediainfo.config import SonosConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)


class SonosSource(MediaSource):
    name = "sonos"

    def __init__(self, config: SonosConfig):
        self.config = config

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
        groups = self._discover_groups()
        if groups is None:
            self.last_poll_failed = True
            return None
        try:
            seen: set[str] = set()
            for group in groups:
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
            self.last_poll_failed = True
            return None

    def _discover_groups(self):
        # Any speaker in the household can report the full zone topology,
        # so try each configured speaker as a discovery seed until one
        # answers - this keeps every zone visible even if a particular
        # speaker is temporarily off or unreachable.
        for ip in self.config.speaker_ips:
            try:
                return SoCo(ip).all_groups
            except Exception:
                logger.debug("Sonos seed %s unreachable, trying next", ip)
        logger.warning("Sonos: no configured speaker_ips were reachable")
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
