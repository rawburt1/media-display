"""MusicBrainz Cover Art Archive enricher: adds album cover scans for music."""

from __future__ import annotations

import logging
from typing import Optional

import requests

from mediainfo.config import MusicBrainzConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)

_MB_SEARCH_URL = "https://musicbrainz.org/ws/2/release-group/"
_CAA_FRONT_URL = "https://coverartarchive.org/release-group/{mbid}/front"
_USER_AGENT = "mediainfo/1.0 (personal use)"


class MusicBrainzEnricher(ArtworkEnricher):
    def __init__(self, config: MusicBrainzConfig):
        self.config = config

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "music":
            return

        try:
            mbid = now_playing.ids.get("musicbrainzalbum")
            if not mbid:
                mbid = self._resolve_release_group(now_playing.subtitle, now_playing.album)
                if not mbid:
                    return

            image_url = self._fetch_front_cover(mbid)
            if image_url and not any(img.url == image_url for img in now_playing.images):
                now_playing.images.append(Artwork(url=image_url, label="Album art (MusicBrainz)"))
        except Exception:
            logger.exception("MusicBrainz enrichment error")

    @staticmethod
    def _resolve_release_group(artist: str, album: str) -> Optional[str]:
        if not artist or not album:
            return None

        query = f'artist:"{artist}" AND release:"{album}"'
        try:
            response = requests.get(
                _MB_SEARCH_URL,
                params={"query": query, "fmt": "json", "limit": 5},
                headers={"User-Agent": _USER_AGENT},
                timeout=10,
            )
            response.raise_for_status()
            groups = response.json().get("release-groups") or []
        except Exception:
            logger.exception("MusicBrainz lookup failed for %r - %r", artist, album)
            return None

        if not groups:
            return None

        # Prefer a studio album over compilations/live recordings.
        group = next((g for g in groups if g.get("primary-type") == "Album"), groups[0])
        return group.get("id")

    @staticmethod
    def _fetch_front_cover(mbid: str) -> Optional[str]:
        """Return the final URL of the front cover, or None if not available."""
        url = _CAA_FRONT_URL.format(mbid=mbid)
        try:
            resp = requests.head(url, allow_redirects=True, timeout=10)
            if resp.status_code == 200:
                return resp.url
        except Exception:
            logger.debug("CAA request failed for %s", mbid)
        return None
