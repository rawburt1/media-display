"""Lyrics enricher: adds lyrics for the currently playing track.

Uses the free lyrics.ovh API (no key required). Genius's official API is
deliberately not used here - it only returns a link to their lyrics page,
not the lyrics text itself, since scraping that page would violate their
terms of service.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional
from urllib.parse import quote

import requests

from mediainfo.config import LyricsConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import NowPlaying

logger = logging.getLogger(__name__)

_API_URL = "https://api.lyrics.ovh/v1/{artist}/{title}"


class LyricsEnricher(ArtworkEnricher):
    def __init__(self, config: LyricsConfig):
        self.config = config
        # Cache misses too (None), keyed by (artist, title), so a song with
        # no lyrics available isn't re-requested on every replay.
        self._cache: Dict[tuple, Optional[str]] = {}

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "music":
            return
        artist = now_playing.subtitle
        title = now_playing.title
        if not artist or not title:
            return

        key = (artist, title)
        if key in self._cache:
            now_playing.lyrics = self._cache[key] or ""
            return

        lyrics = self._fetch(artist, title)
        self._cache[key] = lyrics
        now_playing.lyrics = lyrics or ""

    def _fetch(self, artist: str, title: str) -> Optional[str]:
        url = _API_URL.format(artist=quote(artist), title=quote(title))
        try:
            response = requests.get(url, timeout=8)
            if response.status_code == 404:
                return None
            response.raise_for_status()
        except Exception:
            logger.exception("Lyrics lookup failed for %r - %r", artist, title)
            return None

        lyrics = (response.json() or {}).get("lyrics", "")
        return lyrics.strip() or None
