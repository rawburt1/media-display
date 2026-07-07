"""LRCLIB lyrics enricher: looks up plain and time-synced lyrics for the
currently playing music track via LRCLIB's free, public API
(https://lrclib.net) - no API key needed, and explicitly intended for
this kind of lookup/display use (crowd-sourced, permissively licensed),
unlike scraping a lyrics site of unclear licensing (see roadmap item 8).

Results are cached locally (see TextCache) since the same song is looked
up again on every replay, and LRCLIB is a shared community resource - the
cache avoids leaning on it any harder than necessary.

Only applies to media_type == "music" - other media types are left
untouched. If LRCLIB has no entry for the track (a 404 from the exact-
match endpoint, or no results from search), NowPlaying.lyrics/
synced_lyrics are simply left at their existing empty defaults - never
guessed at or filled from a fuzzy/uncertain match, and instrumental
tracks (which LRCLIB itself flags) naturally end up with nothing to
show either.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from mediainfo.config import LrclibConfig
from mediainfo.enrichers.text_base import TextEnricher
from mediainfo.models import NowPlaying
from mediainfo.text_cache import TextCache

logger = logging.getLogger(__name__)

_BASE_URL = "https://lrclib.net/api"
_NAMESPACE = "lrclib"


def fetch_exact(artist: str, title: str, album: str, duration_seconds: float) -> Optional[dict]:
    """Exact-match lookup by artist/track/album/duration - LRCLIB's
    preferred endpoint when duration is known, since it avoids picking
    the wrong result among cover versions/remixes. A pure, NowPlaying-
    independent function, so it's directly reusable outside the enricher
    (see mediainfo/media_data_store.py's lyrics fetch)."""
    params: dict[str, Any] = {
        "artist_name": artist,
        "track_name": title,
        "duration": int(duration_seconds),
    }
    if album:
        params["album_name"] = album
    response = requests.get(f"{_BASE_URL}/get", params=params, timeout=10)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def fetch_search(artist: str, title: str) -> Optional[dict]:
    """Fuzzy search by artist/track name, used when duration is unknown
    (or the exact-match lookup found nothing) - takes the first (best-
    ranked) result, if any."""
    params = {"artist_name": artist, "track_name": title}
    response = requests.get(f"{_BASE_URL}/search", params=params, timeout=10)
    response.raise_for_status()
    results = response.json()
    return results[0] if results else None


class LrclibEnricher(TextEnricher):
    name = "lrclib"
    config_class = LrclibConfig

    def __init__(self, config: LrclibConfig, cache: Optional[TextCache] = None):
        self.config = config
        self.cache = cache

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "music":
            return
        # subtitle holds the artist for music items - see NowPlaying's
        # own docstring for why.
        artist, title = now_playing.subtitle, now_playing.title
        if not artist or not title:
            return

        cache_key = f"{artist}|{title}|{now_playing.album}"
        if self.cache is not None:
            cached = self.cache.get(_NAMESPACE, cache_key)
            if cached is not None:
                self._apply(now_playing, cached)
                return

        result = self._lookup(now_playing)
        if result is None:
            return
        if self.cache is not None:
            self.cache.set(_NAMESPACE, cache_key, result)
        self._apply(now_playing, result)

    @staticmethod
    def _apply(now_playing: NowPlaying, result: dict) -> None:
        now_playing.lyrics = result.get("plainLyrics") or ""
        now_playing.synced_lyrics = result.get("syncedLyrics") or ""

    def _lookup(self, now_playing: NowPlaying) -> Optional[dict]:
        artist, title, album = now_playing.subtitle, now_playing.title, now_playing.album
        try:
            if now_playing.duration_seconds:
                result = fetch_exact(artist, title, album, now_playing.duration_seconds)
                if result is not None:
                    return result
            return fetch_search(artist, title)
        except Exception:
            logger.exception("LRCLIB lookup failed for %s - %s", artist, title)
            return None
