"""OMDb enricher: adds an IMDb rating (0-10) for movies and TV shows.

Uses ids["imdb"] for a direct lookup when a more specific source/enricher
(e.g. Kodi, Radarr/Sonarr) already provided one; otherwise falls back to a
title search, same pattern as the TMDb and Wikipedia enrichers.

Skips items that already have a rating (e.g. from the TMDb enricher) rather
than overwriting it, and never clears an existing rating on a miss - so
this and enrichers.tmdb can both be enabled at once without one undoing
the other's result depending on which happens to run first.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import requests

from mediainfo.config import OmdbConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import NowPlaying

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.omdbapi.com/"


class OmdbEnricher(ArtworkEnricher):
    name = "omdb"
    config_class = OmdbConfig

    def __init__(self, config: OmdbConfig):
        self.config = config
        # Cache misses too (None), keyed by imdb id or (media_type, title, year).
        self._cache: Dict[tuple, Optional[float]] = {}

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type not in ("movie", "episode"):
            return
        if now_playing.rating is not None:
            return

        imdb_id = now_playing.ids.get("imdb")
        cache_key = (
            ("id", imdb_id)
            if imdb_id
            else ("title", now_playing.media_type, now_playing.title, now_playing.year)
        )

        if cache_key in self._cache:
            rating = self._cache[cache_key]
        else:
            rating = self._lookup(imdb_id, now_playing)
            self._cache[cache_key] = rating

        if rating is not None:
            now_playing.rating = rating

    def _lookup(self, imdb_id: Optional[str], now_playing: NowPlaying) -> Optional[float]:
        try:
            if imdb_id:
                return self._fetch({"i": imdb_id})

            if not now_playing.title:
                return None
            params = {
                "t": now_playing.title,
                "type": "movie" if now_playing.media_type == "movie" else "series",
            }
            if now_playing.media_type == "movie" and now_playing.year:
                params["y"] = str(now_playing.year)
            return self._fetch(params)
        except Exception:
            logger.exception("OMDb enrichment error for %r", now_playing.title)
            return None

    def _fetch(self, params: dict) -> Optional[float]:
        response = self._get(params)
        response.raise_for_status()
        data = response.json()
        if data.get("Response") != "True":
            return None
        return self._parse_rating(data.get("imdbRating"))

    def test_connection(self) -> Tuple[bool, str]:
        try:
            # tt0133093 is The Matrix's IMDb id - a stable, well-known
            # test target, same one used by the tmdb/fanarttv checks.
            rating = self._fetch({"i": "tt0133093"})
            if rating is not None:
                return True, f"API reachable - The Matrix rated {rating}/10"
            return False, "No response - check api_key"
        except Exception as exc:
            return False, f"Error: {exc}"

    def _get(self, params: dict):
        return requests.get(_BASE_URL, params={**params, "apikey": self.config.api_key}, timeout=8)

    @staticmethod
    def _parse_rating(value) -> Optional[float]:
        if not value or value == "N/A":
            return None
        try:
            return round(float(value), 1)
        except (TypeError, ValueError):
            return None
