"""Generic Chromecast "now playing" source: polls Cast devices' media
status directly, so anything cast to them (Netflix, Disney+, YouTube,
Spotify Connect, etc.) is picked up regardless of which app is casting -
unlike sources.shield, which only sees apps running locally on an Android
TV device over ADB.
"""

from __future__ import annotations

import logging
from typing import Optional

import pychromecast

from mediainfo.config import ChromecastConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_SECONDS = 5


class ChromecastSource(MediaSource):
    name = "chromecast"

    def __init__(self, config: ChromecastConfig):
        self.config = config
        self._casts: dict = {}

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
        any_reachable = False

        for ip in self.config.device_ips:
            cast = self._get_cast(ip)
            if cast is None:
                continue
            any_reachable = True

            try:
                cast.media_controller.update_status()
                result = self._from_status(cast)
            except Exception:
                logger.exception("Chromecast source error for %s", ip)
                self._casts.pop(ip, None)
                continue

            if result is not None:
                return result

        if self.config.device_ips and not any_reachable:
            self.last_poll_failed = True
        return None

    def _get_cast(self, ip: str):
        cast = self._casts.get(ip)
        if cast is not None:
            return cast

        try:
            cast = pychromecast.get_chromecast_from_host((ip, 8009, None, None, None))
            cast.wait(timeout=_CONNECT_TIMEOUT_SECONDS)
        except Exception:
            logger.debug("Chromecast at %s unreachable", ip)
            return None

        self._casts[ip] = cast
        return cast

    def _from_status(self, cast) -> Optional[NowPlaying]:
        status = cast.media_controller.status
        app_name = cast.app_display_name or ""
        if app_name in self.config.ignore_apps:
            return None
        if status.player_state != "PLAYING":
            return None

        images = []
        if status.images:
            images.append(Artwork(url=status.images[0].url, label=f"Artwork (Cast: {app_name})"))

        if status.media_is_musictrack:
            return NowPlaying(
                source=self.name,
                media_type="music",
                title=status.title or "",
                subtitle=status.artist or "",
                album=status.album_name or "",
                images=images,
            )

        if status.media_is_tvshow:
            season = status.season
            episode = status.episode
            ep_title = status.title or ""
            if season is not None and episode is not None:
                subtitle = f"S{int(season):02d}E{int(episode):02d} - {ep_title}"
            else:
                subtitle = ep_title
            return NowPlaying(
                source=self.name,
                media_type="episode",
                title=status.series_title or ep_title,
                subtitle=subtitle,
                images=images,
                season=int(season) if season is not None else None,
            )

        title = status.title or app_name
        if not title:
            return None
        return NowPlaying(
            source=self.name,
            media_type="movie",
            title=title,
            subtitle=app_name,
            images=images,
        )
