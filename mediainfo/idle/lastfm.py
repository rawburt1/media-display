"""Last.fm scrobble history idle wallpaper source.

Shows album art from your recent Last.fm scrobbles on outputs while nothing
is currently playing. Requires a free API key and the Last.fm username whose
history to show - see https://www.last.fm/api/account/create.

API docs: https://www.last.fm/api/show/user.getrecenttracks
"""

from __future__ import annotations

import logging
from typing import List

import requests

from mediainfo.config import LastFmHistoryConfig
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import Artwork

logger = logging.getLogger(__name__)

_API_URL = "https://ws.audioscrobbler.com/2.0/"
# Hash used in the URL of Last.fm's default "no image" placeholder.
_PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f"
# Preferred sizes in descending order of quality.
_SIZE_PREFERENCE = ("extralarge", "large", "medium", "small")


class LastFmWallpaperSource(IdleWallpaperSource):
    name = "lastfm"

    def __init__(self, config: LastFmHistoryConfig):
        self.config = config
        self.rotation_interval_seconds = config.rotation_interval_seconds

    def get_wallpapers(self) -> List[Artwork]:
        try:
            params: dict = {
                "method": "user.getrecenttracks",
                "user": self.config.username,
                "api_key": self.config.api_key,
                "limit": self.config.batch_size,
                "format": "json",
            }
            response = requests.get(_API_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception:
            logger.exception("Failed to fetch Last.fm scrobble history")
            return []

        if "error" in data:
            logger.warning("Last.fm error %s: %s", data.get("error"), data.get("message"))
            return []

        tracks = (data.get("recenttracks") or {}).get("track") or []
        if isinstance(tracks, dict):
            tracks = [tracks]

        artworks = []
        seen_urls = set()
        for track in tracks:
            url = self._best_image(track.get("image") or [])
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            artist = (track.get("artist") or {}).get("#text", "")
            name = track.get("name", "")
            label = f"Last.fm: {artist} – {name}" if artist else "Last.fm"
            artworks.append(Artwork(url=url, label=label))

        return artworks

    @staticmethod
    def _best_image(images: list) -> str:
        by_size = {img.get("size"): img.get("#text", "") for img in images}
        for size in _SIZE_PREFERENCE:
            url = by_size.get(size, "")
            if url and _PLACEHOLDER_HASH not in url:
                return url
        return ""
