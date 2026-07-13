"""VLC media player "now playing" source, via its built-in Lua HTTP
interface (Tools -> Preferences -> Show settings: All -> Interface ->
Main interfaces -> check "Web", then set a password under Lua -> Lua HTTP).

VLC's /requests/status.json requires HTTP Basic auth with an empty
username and that password - there is no username field in VLC itself.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from mediainfo.config import VlcConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# Mirrors every other source: "paused"/"stopped" are treated as idle.
_ACTIVE_STATES = {"playing"}


class VlcSource(MediaSource):
    config_class = VlcConfig
    name = "vlc"

    def __init__(self, config: VlcConfig):
        self.config = config
        self._base_url = f"http://{config.host}:{config.port}"
        self._auth = ("", config.password) if config.password else None

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
        try:
            response = requests.get(
                f"{self._base_url}/requests/status.json",
                auth=self._auth,
                timeout=self.config.timeout,
            )
            if response.status_code == 401:
                logger.error(
                    "VLC source: authentication failed - check that sources.vlc.password "
                    "matches VLC's Lua HTTP password (Preferences -> Lua -> Lua HTTP)"
                )
                self.last_poll_failed = True
                return None
            response.raise_for_status()
            status = response.json()

            if status.get("state") not in _ACTIVE_STATES:
                return None

            meta = ((status.get("information") or {}).get("category") or {}).get("meta") or {}

            artist = meta.get("artist", "") or ""
            album = meta.get("album", "") or ""
            title = meta.get("title") or meta.get("filename") or ""

            # Internet radio streams often leave title/artist empty and
            # instead put a combined "Artist - Title" string here.
            now_playing = meta.get("now_playing")
            if now_playing and not title:
                if " - " in now_playing:
                    split_artist, _, split_title = now_playing.partition(" - ")
                    artist = artist or split_artist
                    title = split_title
                else:
                    title = now_playing

            if not title:
                return None

            media_type = "music" if (artist or album) else "movie"

            elapsed = status.get("time")
            duration = status.get("length")

            return NowPlaying(
                source=self.name,
                media_type=media_type,
                title=title,
                subtitle=artist,
                album=album,
                artist=artist,
                images=self._get_artwork(),
                position_seconds=float(elapsed) if elapsed is not None else None,
                duration_seconds=float(duration) if duration is not None else None,
            )
        except Exception:
            logger.exception("VLC source error")
            self.last_poll_failed = True
            return None

    def _get_artwork(self) -> list:
        # VLC serves the current item's artwork directly at /art (whatever
        # image is embedded in the file, or none - a 404 there just means
        # no artwork, which the usual enrichers get a chance to find
        # instead, same as any other source with patchy artwork support).
        return [Artwork(url=f"{self._base_url}/art", auth=self._auth, label="Artwork (VLC)")]
