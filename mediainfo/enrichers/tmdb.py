"""TMDb enricher: adds an audience rating (0-10) for movies and TV shows.

Uses ids["tmdb"] for a direct lookup when a more specific source/enricher
(e.g. Kodi, Radarr/Sonarr) already provided one; otherwise falls back to a
title search, same pattern as the Wikipedia enricher.

Skips items that already have a rating (e.g. from the OMDb enricher) rather
than overwriting it, and never clears an existing rating on a miss - so
this and enrichers.omdb can both be enabled at once without one undoing
the other's result depending on which happens to run first.

Optionally (config.fetch_cast, off by default) also populates
NowPlaying.cast - top-billed cast members with name/character/headshot,
used by the Cast/Crew Mosaic Display Theme. This is a fully independent
code path from the rating logic above (own cache, own id-resolution
fallback) so it can't affect the already-established rating behavior.
TV credits are show-level (/tv/{id}/credits - the show's regular cast),
not per-episode guest stars - TMDb's per-episode credits endpoint needs a
season+episode number NowPlaying doesn't track, a deliberate v1
simplification (same spirit as other themes' own documented
simplifications, e.g. Vinyl's lack of real play/pause detection).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import requests

from mediainfo.config import TmdbConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import NowPlaying

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.themoviedb.org/3"
_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"


def _get(api_key: str, url: str, params: Optional[dict] = None):
    # TMDb's dashboard hands out two different kinds of credential for
    # the same account: a short v3 "API Key" (passed as an ?api_key=
    # query param) and a long v4 "API Read Access Token" (a JWT, passed
    # as a Bearer header instead) - support whichever the user has,
    # since it's easy to grab the wrong one from their settings page.
    if api_key.count(".") == 2:
        headers = {"Authorization": f"Bearer {api_key}"}
        return requests.get(url, params=params, headers=headers, timeout=8)
    return requests.get(url, params={**(params or {}), "api_key": api_key}, timeout=8)


def search(api_key: str, endpoint: str, title: str, year: Optional[int] = None) -> list:
    """Search TMDb's public catalog (endpoint: "movie" or "tv") by title,
    optionally narrowed by release year (movies only - TMDb's /search/tv
    doesn't accept a year filter)."""
    params: dict = {"query": title}
    if endpoint == "movie" and year:
        params["year"] = str(year)
    response = _get(api_key, f"{_BASE_URL}/search/{endpoint}", params)
    response.raise_for_status()
    return response.json().get("results", [])


def fetch_rating(api_key: str, url: str) -> Optional[float]:
    response = _get(api_key, url)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return _round(response.json().get("vote_average"))


def fetch_cast(api_key: str, endpoint: str, tmdb_id: str, limit: int) -> List[Dict[str, str]]:
    """Top-billed cast for a movie/TV show (endpoint: "movie" or "tv"),
    capped to `limit`, most-prominent first (TMDb's own `cast` list is
    already ordered by billing). Entries with no name are skipped;
    `photo_url` is "" when TMDb has no headshot on file for that person.

    Uses TMDb's "h632" profile size (~421x632 for a standard 2:3
    headshot), not the smaller "w185" thumbnail used for e.g. the config
    UI's own tiny previews - ImageCache's default min_width/min_height
    (400x400, see mediainfo/cache.py) would silently reject "w185"
    (185px wide) entirely, so every cast photo would 404 through the
    Cast/Crew Mosaic theme."""
    response = _get(api_key, f"{_BASE_URL}/{endpoint}/{tmdb_id}/credits")
    if response.status_code == 404:
        return []
    response.raise_for_status()
    cast = response.json().get("cast", [])[:limit]
    return [
        {
            "name": member["name"],
            "character": member.get("character", ""),
            "photo_url": image_url(member.get("profile_path"), "h632") or "",
        }
        for member in cast
        if member.get("name")
    ]


def _best_match(results: list, year: Optional[int], date_field: str) -> Optional[dict]:
    if not results:
        return None
    if year:
        for result in results:
            date = result.get(date_field) or ""
            if date[:4] == str(year):
                return result
    return results[0]


def find_movie(api_key: str, title: str, year: Optional[int]) -> Optional[dict]:
    """Search for a movie by title (+ optional year), returning the
    best-matching result dict (with poster_path/backdrop_path/id), or
    None. No episode/subtitle info is available here to disambiguate
    further (unlike thetvdb's search) - if a year is given, prefer a
    result whose release_date starts with it, else take the top result."""
    results = search(api_key, "movie", title, year)
    return _best_match(results, year, "release_date")


def find_tv(api_key: str, title: str) -> Optional[dict]:
    """Search for a TV show by title, returning the best-matching result
    dict (with poster_path/backdrop_path/id), or None. No year filter -
    TMDb's /search/tv doesn't support one, and NowPlaying.year is rarely
    populated for episodes anyway - just takes the top result."""
    results = search(api_key, "tv", title)
    return _best_match(results, None, "first_air_date")


def image_url(path: Optional[str], size: str) -> Optional[str]:
    """Build a full TMDb image CDN URL from a poster_path/backdrop_path,
    or None if there's no path."""
    return f"{_IMAGE_BASE_URL}/{size}{path}" if path else None


def artwork_url(result: Optional[dict], kind: str) -> Optional[str]:
    """Pick the right field/CDN size for `kind` ("poster" or "fanart") out
    of a find_movie()/find_tv() result dict, or None if there's no result
    or no image at that field."""
    if not result:
        return None
    path_field = "poster_path" if kind == "poster" else "backdrop_path"
    size = "w500" if kind == "poster" else "w1280"
    return image_url(result.get(path_field), size)


def _round(value) -> Optional[float]:
    if not value:
        return None
    return round(value, 1)


class TmdbEnricher(ArtworkEnricher):
    def __init__(self, config: TmdbConfig):
        self.config = config
        # Cache misses too (None), keyed by (media_type, tmdb id or title).
        self._cache: Dict[tuple, Optional[float]] = {}
        # Independent cache for the optional cast fetch below - keyed the
        # same way, but never shares an entry with _cache (one holds a
        # rating, the other a cast list).
        self._cast_cache: Dict[tuple, List[Dict[str, str]]] = {}

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type not in ("movie", "episode"):
            return

        endpoint = "movie" if now_playing.media_type == "movie" else "tv"

        if now_playing.rating is None:
            tmdb_id = now_playing.ids.get("tmdb")
            cache_key = (endpoint, tmdb_id or now_playing.title)
            if cache_key in self._cache:
                rating = self._cache[cache_key]
            else:
                rating = self._lookup(endpoint, tmdb_id, now_playing)
                self._cache[cache_key] = rating
            if rating is not None:
                now_playing.rating = rating

        if self.config.fetch_cast and not now_playing.cast:
            now_playing.cast = self._lookup_cast(endpoint, now_playing)

    def _lookup(
        self, endpoint: str, tmdb_id: Optional[str], now_playing: NowPlaying
    ) -> Optional[float]:
        try:
            if tmdb_id:
                return fetch_rating(self.config.api_key, f"{_BASE_URL}/{endpoint}/{tmdb_id}")

            if not now_playing.title:
                return None
            results = search(self.config.api_key, endpoint, now_playing.title, now_playing.year)
            if not results:
                return None
            return _round(results[0].get("vote_average"))
        except Exception:
            logger.exception("TMDb enrichment error for %r", now_playing.title)
            return None

    def _lookup_cast(self, endpoint: str, now_playing: NowPlaying) -> List[Dict[str, str]]:
        cache_key = (endpoint, now_playing.ids.get("tmdb") or now_playing.title, now_playing.year)
        if cache_key in self._cast_cache:
            return self._cast_cache[cache_key]

        cast = self._fetch_cast(endpoint, now_playing)
        self._cast_cache[cache_key] = cast
        return cast

    def _fetch_cast(self, endpoint: str, now_playing: NowPlaying) -> List[Dict[str, str]]:
        try:
            tmdb_id = now_playing.ids.get("tmdb") or self._resolve_id_via_search(
                endpoint, now_playing
            )
            if not tmdb_id:
                return []
            return fetch_cast(self.config.api_key, endpoint, tmdb_id, self.config.cast_size)
        except Exception:
            logger.exception("TMDb cast enrichment error for %r", now_playing.title)
            return []

    def _resolve_id_via_search(self, endpoint: str, now_playing: NowPlaying) -> Optional[str]:
        if not now_playing.title:
            return None
        date_field = "release_date" if endpoint == "movie" else "first_air_date"
        results = search(self.config.api_key, endpoint, now_playing.title, now_playing.year)
        result = _best_match(results, now_playing.year, date_field)
        return str(result["id"]) if result and result.get("id") else None

    def test_connection(self) -> Tuple[bool, str]:
        try:
            # 603 is The Matrix's TMDb id - a stable, well-known test target.
            rating = fetch_rating(self.config.api_key, f"{_BASE_URL}/movie/603")
            if rating is not None:
                return True, f"API reachable - The Matrix rated {rating}/10"
            return False, "No response - check api_key"
        except Exception as exc:
            return False, f"Error: {exc}"
