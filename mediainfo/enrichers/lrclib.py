"""Synced lyrics enricher: adds time-synced (LRC-format) lyrics for the
currently playing track, alongside the plain-text lyrics enricher.

Uses the free lrclib.net API (no key required) - unlike lyrics.ovh (see
lyrics.py), it returns lyrics with per-line "[mm:ss.xx] text" timestamps
when available, which the info output uses to highlight/scroll the
current line in time with playback (see NowPlaying.lyrics_synced and
models.NowPlaying.position_seconds).

Many tracks have no synced lyrics on lrclib even when plain lyrics exist
elsewhere - that's a normal miss, not an error, so this enricher leaves
lyrics_synced empty rather than falling back to anything else; the info
output's template falls back to the plain lyrics enricher's output when
this is empty.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import requests

from mediainfo.config import LrclibConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import NowPlaying
from mediainfo.musiclibrary import MusicLibrary

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://lrclib.net/api/search"
_HEADERS = {"User-Agent": "mediainfo/1.0 (+https://github.com/rawburt1/media-display)"}


class LrclibEnricher(ArtworkEnricher):
    def __init__(self, config: LrclibConfig, library: Optional[MusicLibrary] = None):
        self.config = config
        self.library = library
        # Used only when no library is available - cache misses too (None),
        # keyed by (artist, title), so a song with no synced lyrics found
        # isn't re-requested on every replay within this process.
        self._cache: Dict[tuple, Optional[str]] = {}

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "music":
            return
        artist = now_playing.subtitle
        title = now_playing.title
        if not artist or not title:
            return

        now_playing.lyrics_synced = self._synced_lyrics_for(artist, title) or ""

    def _synced_lyrics_for(self, artist: str, title: str) -> Optional[str]:
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
            "track", track_id, "lyrics_synced", "lrclib",
            lambda: self._fetch(artist, title),
            max_age_seconds=float("inf"),
        )

    def _fetch(self, artist: str, title: str) -> Optional[str]:
        try:
            response = requests.get(
                _SEARCH_URL,
                params={"track_name": title, "artist_name": artist},
                headers=_HEADERS,
                timeout=8,
            )
            response.raise_for_status()
            results = response.json() or []
        except Exception:
            logger.exception("lrclib lookup failed for %r - %r", artist, title)
            return None

        for result in results:
            synced = (result.get("syncedLyrics") or "").strip()
            if synced:
                return synced
        return None
