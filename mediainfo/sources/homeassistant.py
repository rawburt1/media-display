"""Home Assistant "now playing" source: polls a single media_player entity's
state via HA's REST API.

Useful as a fallback for devices a more specific source can't read "now
playing" from directly - e.g. a tvOS app like SVT Play that never populates
Apple's own now-playing API, which leaves pyatv (see sources.appletv) only
ever seeing the device as idle. Home Assistant's own Apple TV integration
can still see it (apparently via a long-since-established MRP pairing this
codebase can no longer make fresh, since the device stopped advertising MRP
over mDNS at some point) - polling that entity through HA's API sidesteps
the problem entirely, at the cost of depending on HA staying up.

Not specific to Apple TV: this works for any media_player entity HA tracks.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from mediainfo.config import HomeAssistantConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# HA media_player states that count as "actually playing" - paused/idle/off/
# standby/buffering/unavailable are all treated as "nothing playing" rather
# than an error (see MediaSource.last_poll_failed's docstring).
_PLAYING_STATES = frozenset(["playing"])


class HomeAssistantSource(MediaSource):
    name = "homeassistant"

    def __init__(self, config: HomeAssistantConfig):
        self.config = config
        scheme = "https" if config.use_ssl else "http"
        self._base = f"{scheme}://{config.host}:{config.port}"

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
        try:
            response = requests.get(
                f"{self._base}/api/states/{self.config.entity_id}",
                headers={"Authorization": f"Bearer {self.config.token}"},
                timeout=5,
            )
            response.raise_for_status()
            entity = response.json()

            if entity.get("state") not in _PLAYING_STATES:
                return None

            return self._parse_entity(entity.get("attributes") or {})
        except Exception:
            logger.exception("Home Assistant source error")
            self.last_poll_failed = True
            return None

    def _parse_entity(self, attrs: dict) -> NowPlaying:
        images = []
        picture = attrs.get("entity_picture")
        if picture:
            images.append(Artwork(url=f"{self._base}{picture}", label="Artwork (Home Assistant)"))

        content_type = (attrs.get("media_content_type") or "").lower()
        series_title = attrs.get("media_series_title")

        if series_title or content_type in ("tvshow", "episode"):
            season = attrs.get("media_season")
            episode = attrs.get("media_episode")
            ep_title = attrs.get("media_title", "") or ""
            if season is not None and episode is not None:
                subtitle = f"S{int(season):02d}E{int(episode):02d} - {ep_title}"
            else:
                subtitle = ep_title
            return NowPlaying(
                source=self.name,
                media_type="episode",
                title=series_title or attrs.get("media_title", ""),
                subtitle=subtitle,
                images=images,
                season=int(season) if season is not None else None,
            )

        if content_type == "music" or attrs.get("media_artist"):
            return NowPlaying(
                source=self.name,
                media_type="music",
                title=attrs.get("media_title", "") or "",
                subtitle=attrs.get("media_artist", "") or "",
                album=attrs.get("media_album_name", "") or "",
                images=images,
            )

        return NowPlaying(
            source=self.name,
            media_type="movie",
            title=attrs.get("media_title", "") or attrs.get("app_name", "") or "",
            subtitle=attrs.get("app_name", "") or "",
            images=images,
        )
