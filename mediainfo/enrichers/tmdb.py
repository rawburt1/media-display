"""TMDb enricher: adds an audience rating (0-10) for movies and TV shows.

Uses ids["tmdb"] for a direct lookup when a more specific source/enricher
(e.g. Kodi, Radarr/Sonarr) already provided one; otherwise falls back to a
title search, same pattern as the Wikipedia enricher.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import requests

from mediainfo.config import TmdbConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import NowPlaying

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.themoviedb.org/3"


class TmdbEnricher(ArtworkEnricher):
    def __init__(self, config: TmdbConfig):
        self.config = config
        # Cache misses too (None), keyed by (media_type, tmdb id or title).
        self._cache: Dict[tuple, Optional[float]] = {}

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type not in ("movie", "episode"):
            return

        endpoint = "movie" if now_playing.media_type == "movie" else "tv"
        tmdb_id = now_playing.ids.get("tmdb")
        cache_key = (endpoint, tmdb_id or now_playing.title)

        if cache_key in self._cache:
            now_playing.rating = self._cache[cache_key]
            return

        rating = self._lookup(endpoint, tmdb_id, now_playing)
        self._cache[cache_key] = rating
        now_playing.rating = rating

    def _lookup(
        self, endpoint: str, tmdb_id: Optional[str], now_playing: NowPlaying
    ) -> Optional[float]:
        try:
            if tmdb_id:
                return self._fetch_rating(f"{_BASE_URL}/{endpoint}/{tmdb_id}")

            if not now_playing.title:
                return None
            params: dict = {"query": now_playing.title}
            if endpoint == "movie" and now_playing.year:
                params["year"] = str(now_playing.year)
            results = self._search(endpoint, params)
            if not results:
                return None
            return self._round(results[0].get("vote_average"))
        except Exception:
            logger.exception("TMDb enrichment error for %r", now_playing.title)
            return None

    def _search(self, endpoint: str, params: dict) -> list:
        response = requests.get(
            f"{_BASE_URL}/search/{endpoint}",
            params={**params, "api_key": self.config.api_key},
            timeout=8,
        )
        response.raise_for_status()
        return response.json().get("results", [])

    def _fetch_rating(self, url: str) -> Optional[float]:
        response = requests.get(url, params={"api_key": self.config.api_key}, timeout=8)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return self._round(response.json().get("vote_average"))

    @staticmethod
    def _round(value) -> Optional[float]:
        if not value:
            return None
        return round(value, 1)
