"""Lyrics enricher: adds lyrics for the currently playing track.

Uses the free lyrics.ovh API (no key required). Genius's official API is
deliberately not used here - it only returns a link to their lyrics page,
not the lyrics text itself, since scraping that page would violate their
terms of service.

When a MusicLibrary is available, a found lyrics result is persisted there
forever (a song's lyrics don't change) rather than just for the life of
the process - same mechanism the other music enrichers use for cover art/
artist photos, but with no expiry, so lyrics survive a restart and are
never re-fetched.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional
from urllib.parse import quote

import requests

from mediainfo.config import LyricsConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import NowPlaying
from mediainfo.musiclibrary import MusicLibrary

logger = logging.getLogger(__name__)

_API_URL = "https://api.lyrics.ovh/v1/{artist}/{title}"


class LyricsEnricher(ArtworkEnricher):
    def __init__(self, config: LyricsConfig, library: Optional[MusicLibrary] = None):
        self.config = config
        self.library = library
        # Used only when no library is available - cache misses too (None),
        # keyed by (artist, title), so a song with no lyrics found isn't
        # re-requested on every replay within this process.
        self._cache: Dict[tuple, Optional[str]] = {}

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "music":
            return
        artist = now_playing.subtitle
        title = now_playing.title
        if not artist or not title:
            return

        now_playing.lyrics = self._lyrics_for(artist, title) or ""

    def _lyrics_for(self, artist: str, title: str) -> Optional[str]:
        if self.library is None:
            key = (artist, title)
            if key in self._cache:
                return self._cache[key]
            lyrics = self._fetch(artist, title)
            self._cache[key] = lyrics
            return lyrics

        artist_id = self.library.get_or_create_artist(artist)
        track_id = self.library.get_or_create_track(artist_id, title)
        return self.library.get_or_fetch(
            "track", track_id, "lyrics", "lyrics.ovh",
            lambda: self._fetch(artist, title),
            max_age_seconds=float("inf"),
        )

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
