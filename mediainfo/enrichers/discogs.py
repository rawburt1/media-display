"""Discogs enricher: adds album cover art for music from the Discogs database.

Searches the Discogs master-release index by artist + album name, then appends
the canonical cover image.  Requires a personal access token (free) and both
`subtitle` (artist) and `album` to be set on the NowPlaying item — without a
precise album name the search is skipped to avoid adding artwork for the wrong
release.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from mediainfo.config import DiscogsConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.discogs.com/database/search"
_USER_AGENT = "mediainfo/1.0 (personal use)"


class DiscogsEnricher(ArtworkEnricher):
    def __init__(self, config: DiscogsConfig) -> None:
        self.config = config

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "music":
            return

        artist = now_playing.subtitle
        album = now_playing.album
        if not artist or not album:
            return

        try:
            url = self._find_cover(artist, album)
            if url and not any(img.url == url for img in now_playing.images):
                now_playing.images.append(Artwork(url=url, label="Album art (Discogs)"))
        except Exception:
            logger.exception("Discogs enrichment error")

    def _find_cover(self, artist: str, album: str) -> Optional[str]:
        # Masters represent canonical releases and have better, deduplicated artwork.
        url = self._search(artist, album, "master")
        if url:
            return url
        # Fall back to individual releases for albums that have no master entry.
        return self._search(artist, album, "release")

    def _search(self, artist: str, album: str, result_type: str) -> Optional[str]:
        try:
            resp = requests.get(
                _SEARCH_URL,
                params={
                    "type": result_type,
                    "artist": artist,
                    "release_title": album,
                    "token": self.config.token,
                },
                headers={"User-Agent": _USER_AGENT},
                timeout=10,
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
        except Exception:
            logger.exception("Discogs search failed for %r – %r", artist, album)
            return None

        for result in results:
            cover = result.get("cover_image") or result.get("thumb") or ""
            if cover and _is_real_image(cover):
                return cover
        return None


def _is_real_image(url: str) -> bool:
    """Return False for empty strings and known Discogs placeholder images."""
    return bool(url) and not any(p in url for p in ("spacer.gif", "noimage", "default-release"))
