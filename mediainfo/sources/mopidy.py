"""Mopidy "now playing" source via its core JSON-RPC API
(https://docs.mopidy.com/en/latest/api/core/), served over HTTP by
Mopidy's built-in web server at /mopidy/rpc.

Mopidy is a backend-agnostic music server - the same JSON-RPC surface
reports whatever's playing regardless of which backend (Mopidy-Spotify,
Mopidy-local, Mopidy-Subsonic, ...) is actually producing it, so this
source needs no backend-specific handling.
"""

from __future__ import annotations

import logging
from typing import Optional

from mediainfo.config import MopidyConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource
from mediainfo.sources.jsonrpc import JsonRpcClient

logger = logging.getLogger(__name__)

# Mirrors every other source in this codebase (Plex, Jellyfin, HomeAssistant,
# Spotify, ...): "paused" is treated the same as "nothing playing" - the
# idle screen takes over rather than the display freezing on stale artwork.
_ACTIVE_STATES = {"playing"}


class MopidySource(MediaSource):
    name = "mopidy"

    def __init__(self, config: MopidyConfig):
        self.config = config
        self._rpc = JsonRpcClient(
            f"http://{config.host}:{config.port}/mopidy/rpc", timeout=config.timeout
        )

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
        try:
            state = self._rpc.call("core.playback.get_state")
            if state not in _ACTIVE_STATES:
                return None

            track = self._rpc.call("core.playback.get_current_track")
            if not track:
                return None

            artists = track.get("artists") or []
            artist = artists[0].get("name", "") if artists else ""
            album = (track.get("album") or {}).get("name", "")

            position_ms = self._rpc.call("core.playback.get_time_position")
            duration_ms = track.get("length")

            return NowPlaying(
                source=self.name,
                media_type="music",
                title=track.get("name", "") or "",
                subtitle=artist,
                album=album,
                artist=artist,
                images=self._get_images(track.get("uri")),
                position_seconds=position_ms / 1000 if position_ms is not None else None,
                duration_seconds=duration_ms / 1000 if duration_ms is not None else None,
            )
        except Exception:
            logger.exception("Mopidy source error")
            self.last_poll_failed = True
            return None

    def _get_images(self, uri: Optional[str]) -> list:
        """Best-effort album art lookup via core.library.get_images() -
        never fails the whole poll (image URIs vary a lot by backend, some
        backends don't provide any at all - a missing cover just means the
        existing artwork enrichers get a chance to find one instead, same
        as any other source with patchy artwork support).
        """
        if not uri:
            return []
        try:
            result = self._rpc.call("core.library.get_images", [[uri]])
            entries = (result or {}).get(uri) or []
            images = []
            for entry in entries:
                image_uri = entry.get("uri")
                if not image_uri:
                    continue
                if not image_uri.startswith(("http://", "https://")):
                    image_uri = f"http://{self.config.host}:{self.config.port}{image_uri}"
                images.append(Artwork(url=image_uri, label="Album art (Mopidy)"))
            return images
        except Exception:
            logger.exception("Mopidy image lookup error")
            return []
