"""Last.fm enricher: adds artist photos for music tracks.

Uses the artist.getinfo API method to fetch artist images.  Last.fm removed
most artist photos from their API in 2019–2020; the enricher skips the
well-known placeholder image so nothing appears if no real photo is available.

API docs: https://www.last.fm/api/show/artist.getInfo
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from mediainfo.config import LastFmConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying
from mediainfo.musiclibrary import MusicLibrary

logger = logging.getLogger(__name__)

_API_URL = "https://ws.audioscrobbler.com/2.0/"
# Hash used in the URL of the default "no image" placeholder.
_PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f"
# Preferred sizes in descending order of quality.
_SIZE_PREFERENCE = ("mega", "extralarge", "large", "medium", "small")


class LastFmEnricher(ArtworkEnricher):
    def __init__(self, config: LastFmConfig, library: Optional[MusicLibrary] = None):
        self._api_key = config.api_key
        self.library = library

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "music":
            return
        artist = now_playing.subtitle
        if not artist:
            return

        try:
            url = self._image_for(artist)
        except Exception:
            logger.exception("Last.fm enrichment error for %r", artist)
            return

        if url and not any(img.url == url for img in now_playing.images):
            now_playing.images.append(
                Artwork(url=url, label=f"Artist photo (Last.fm): {artist}")
            )

    def _image_for(self, artist: str) -> Optional[str]:
        if self.library is None:
            return self._fetch_artist_image(artist)

        artist_id = self.library.get_or_create_artist(artist)
        return self.library.get_or_fetch(
            "artist", artist_id, "photo_url", "lastfm", lambda: self._fetch_artist_image(artist)
        )

    def _fetch_artist_image(self, artist: str) -> Optional[str]:
        try:
            resp = requests.get(
                _API_URL,
                params={
                    "method": "artist.getinfo",
                    "artist": artist,
                    "api_key": self._api_key,
                    "autocorrect": "1",
                    "format": "json",
                },
                timeout=8,
            )
            resp.raise_for_status()
        except Exception:
            logger.exception("Last.fm API request failed for artist %r", artist)
            return None

        data = resp.json()
        if "error" in data:
            logger.debug("Last.fm error %s: %s", data.get("error"), data.get("message"))
            return None

        images = data.get("artist", {}).get("image", [])
        by_size = {img.get("size"): img.get("#text", "") for img in images}

        for size in _SIZE_PREFERENCE:
            url = by_size.get(size, "")
            if url and _PLACEHOLDER_HASH not in url:
                return url

        return None
