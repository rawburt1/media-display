"""Wikipedia enricher: adds an artist/movie/TV-show summary and photo.

Uses the public Wikipedia REST API (no API key required): a search call
finds the best-matching page title, then the summary endpoint returns a
plain-text extract and a thumbnail image for that page.

Lookups are cached in memory for the life of the process, keyed by the
primary query (artist name / "Title (year film)" / "Title (TV series)").
The orchestrator only re-enriches when the playing item actually changes,
but the same artist/movie/show is looked up again on every replay across
separate play sessions - the cache (including a "nothing found" sentinel
for misses) avoids hitting Wikipedia's API for those repeats. There's no
TTL since Wikipedia summaries for a given title rarely change within a
single run of this process.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from mediainfo.config import WikipediaConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_HEADERS = {"User-Agent": "mediainfo/1.0 (https://github.com/rawburt1/media-display)"}

# (summary text, thumbnail url or None) on a hit; None means "looked up
# before and nothing usable was found" - cached too, to skip a wasted retry.
_CacheEntry = Optional[Tuple[str, Optional[str]]]


class WikipediaEnricher(ArtworkEnricher):
    def __init__(self, config: WikipediaConfig):
        self.config = config
        self._cache: Dict[str, _CacheEntry] = {}

    def enrich(self, now_playing: NowPlaying) -> None:
        queries = self._queries_for(now_playing)
        if not queries:
            return

        cache_key = queries[0]
        if cache_key in self._cache:
            self._apply(now_playing, self._cache[cache_key])
            return

        result = self._lookup(queries)
        self._cache[cache_key] = result
        self._apply(now_playing, result)

    @staticmethod
    def _apply(now_playing: NowPlaying, result: _CacheEntry) -> None:
        if result is None:
            return
        summary, thumbnail = result
        now_playing.summary = summary
        if thumbnail and not any(image.url == thumbnail for image in now_playing.images):
            is_artist_photo = now_playing.media_type == "music" or bool(now_playing.artist)
            now_playing.images.append(
                Artwork(url=thumbnail, label="Photo (Wikipedia)", is_artist_photo=is_artist_photo)
            )

    def _lookup(self, queries: List[str]) -> _CacheEntry:
        try:
            for query in queries:
                title = self._search(query)
                if not title:
                    continue

                summary = self._get_summary(title)
                if not summary or summary.get("type") == "disambiguation":
                    continue

                extract = summary.get("extract")
                if not extract:
                    continue

                # Prefer the full-resolution original over the thumbnail -
                # Wikipedia's REST summary always downsizes the thumbnail to
                # ~320px wide, which the cache's 640x480 minimum-size filter
                # then rejects on every single fetch, discarding a usable
                # originalimage that was right there in the same response.
                thumbnail = (summary.get("originalimage") or {}).get("source") or (
                    summary.get("thumbnail") or {}
                ).get("source")
                return extract, thumbnail
        except Exception:
            logger.exception("Wikipedia enrichment error")
        return None

    @staticmethod
    def _queries_for(np: NowPlaying) -> List[str]:
        if np.media_type == "music":
            if not np.subtitle:
                return []
            # Plain artist name first; many common-word band names (e.g.
            # "Queen") resolve to a disambiguation page, so fall back to
            # genre-specific disambiguators.
            return [np.subtitle, f"{np.subtitle} (band)", f"{np.subtitle} (musician)"]
        if np.artist:
            return [np.artist, f"{np.artist} (band)", f"{np.artist} (musician)"]
        if np.media_type == "movie":
            if not np.title:
                return []
            queries = []
            if np.year:
                queries.append(f"{np.title} ({np.year} film)")
            queries.append(f"{np.title} (film)")
            return queries
        if np.media_type == "episode":
            return [f"{np.title} (TV series)"] if np.title else []
        return []

    def _search(self, query: str) -> Optional[str]:
        params: dict = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 1,
            "format": "json",
        }
        response = requests.get(_SEARCH_URL, params=params, headers=_HEADERS, timeout=10)
        response.raise_for_status()
        results = (response.json().get("query") or {}).get("search") or []
        return results[0]["title"] if results else None

    def _get_summary(self, title: str) -> Optional[dict]:
        url = _SUMMARY_URL.format(title=quote(title.replace(" ", "_")))
        response = requests.get(url, headers=_HEADERS, timeout=10)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
