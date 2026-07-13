"""SVT Play enricher: fetches show poster art from SVT's content API and
optionally resolves the tvdb-id via Sonarr.

Fills in artwork for episodes detected from the SVT Play app when no
other enricher has found any - derives a URL slug from the title and
queries SVT's internal GraphQL API (contento.svt.se/graphql). No API
key or account required; uses a public endpoint.

This covers the common case of SVT shows that are titled in Swedish and
therefore not findable by thetvdb.com's search API by title alone. Two
mechanisms bridge the gap:

1.  Sonarr alternate-title lookup: if a Sonarr host is configured the
    enricher fetches the series list (cached for one hour) and matches
    the Swedish title against each series' main title and its alternate
    titles.  A match fills in `ids["tvdb"]` so enrichers like thetvdb
    and fanarttv can subsequently fetch proper artwork by id.

2.  originalProgramTitle: for SVT `Single` programmes (stand-alone
    films/documentaries) the API returns the original-language title
    (e.g. "Melody Gardot - The Essential at Olympia Paris" for what SVT
    calls "Melody Gardot Live at the Olympia").  This is stored on
    `now_playing.original_title` so the thetvdb enricher can use it as
    a fallback search term.

The SVT CDN artwork is only used when no tvdb-id is available - a
resolved id means thetvdb / fanarttv will provide higher-quality artwork
and SVT's CDN image would just be noise.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from typing import Optional, Tuple

import requests

from mediainfo.config import SvtConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)

_GRAPHQL_URL = "https://contento.svt.se/graphql"
_IMAGE_URL = "https://www.svtstatic.se/image/medium/960/{image_id}"

_IMAGES_QUERY = "images { portrait { id } wide { id } }"

# Sonarr series list is cached for this long before being re-fetched, so
# newly added shows are picked up without needing a full service restart.
_SONARR_CACHE_TTL = 3600  # seconds


class SvtEnricher(ArtworkEnricher):
    name = "svt"
    config_class = SvtConfig

    def __init__(self, config: SvtConfig):
        self.config = config
        # title -> (image_url, original_title), cached per process run
        self._cache: dict[str, Tuple[Optional[str], Optional[str]]] = {}
        self._sonarr_enabled = bool(config.sonarr_host and config.sonarr_api_key)
        self._sonarr_series_cache: Optional[list] = None
        self._sonarr_cache_fetched_at: float = 0.0

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "episode":
            return
        if not now_playing.title:
            return

        # Resolve tvdb-id via Sonarr alternate-title matching before the
        # artwork check - SVT shows have Swedish device titles that thetvdb /
        # fanarttv can't look up without the id.
        if self._sonarr_enabled and not now_playing.ids.get("tvdb"):
            try:
                self._resolve_via_sonarr(now_playing)
            except Exception:
                logger.exception("SVT/Sonarr lookup error for %r", now_playing.title)

        # Skip the SVT CDN artwork lookup when a tvdb-id is known: the show
        # is tracked in an international database and thetvdb / fanarttv will
        # provide higher-quality artwork.  Also skip if artwork was already
        # found by a higher-priority enricher.
        if now_playing.images or now_playing.ids.get("tvdb"):
            return

        try:
            image_url, original_title = self._resolve(now_playing.title)
            if image_url:
                now_playing.images.append(Artwork(url=image_url, label="Poster (SVT)"))
            if original_title and not now_playing.original_title:
                now_playing.original_title = original_title
                logger.info(
                    "SVT: stored original title %r for %r",
                    original_title,
                    now_playing.title,
                )
            # If originalProgramTitle looks like "Artist - Subtitle" (common
            # for SVT music concerts), extract the artist name so Wikipedia
            # and Last.fm can look up artist photos.
            if original_title and not now_playing.artist and " - " in original_title:
                candidate = original_title.split(" - ", 1)[0].strip()
                if candidate:
                    now_playing.artist = candidate
                    logger.info(
                        "SVT: extracted artist %r from original title %r",
                        candidate,
                        original_title,
                    )
        except Exception:
            logger.exception("SVT enrichment error for %r", now_playing.title)

    # ------------------------------------------------------------------
    # Sonarr alternate-title lookup
    # ------------------------------------------------------------------

    def _resolve_via_sonarr(self, now_playing: NowPlaying) -> None:
        series_list = self._fetch_sonarr_series()
        if not series_list:
            return

        target = now_playing.title.strip().casefold()
        for series in series_list:
            if (series.get("title") or "").strip().casefold() == target:
                self._apply_sonarr_match(now_playing, series)
                return
            for alt in series.get("alternateTitles") or []:
                if (alt.get("title") or "").strip().casefold() == target:
                    self._apply_sonarr_match(now_playing, series)
                    return

    def _apply_sonarr_match(self, now_playing: NowPlaying, series: dict) -> None:
        tvdb_id = series.get("tvdbId")
        if tvdb_id:
            now_playing.ids["tvdb"] = str(tvdb_id)
            logger.info(
                "SVT: resolved %r → tvdb %s (%s) via Sonarr",
                now_playing.title,
                tvdb_id,
                series.get("title", ""),
            )

    def _fetch_sonarr_series(self) -> Optional[list]:
        now = time.monotonic()
        if (
            self._sonarr_series_cache is not None
            and (now - self._sonarr_cache_fetched_at) < _SONARR_CACHE_TTL
        ):
            return self._sonarr_series_cache
        url = f"http://{self.config.sonarr_host}:{self.config.sonarr_port}/api/v3/series"
        response = requests.get(
            url,
            headers={"X-Api-Key": self.config.sonarr_api_key},
            timeout=10,
        )
        response.raise_for_status()
        self._sonarr_series_cache = response.json()
        self._sonarr_cache_fetched_at = now
        return self._sonarr_series_cache

    # ------------------------------------------------------------------
    # SVT GraphQL artwork + original title lookup
    # ------------------------------------------------------------------

    def _resolve(self, title: str) -> Tuple[Optional[str], Optional[str]]:
        if title in self._cache:
            return self._cache[title]

        slug = _slugify(title)
        result = self._fetch(slug)
        image_url, original_title = result
        if image_url:
            logger.info("SVT: found artwork for %r (slug %r)", title, slug)
        else:
            logger.debug("SVT: no match for %r (slug %r)", title, slug)
        self._cache[title] = result
        return result

    def _fetch(self, slug: str) -> Tuple[Optional[str], Optional[str]]:
        # Query both TvSeries and Single (stand-alone films/documentaries).
        # Single also exposes originalProgramTitle which thetvdb can search.
        query = (
            '{ contentBySlug(slugs: ["%s"]) {'
            " ... on TvSeries { %s }"
            " ... on Single { originalProgramTitle %s }"
            "} }" % (slug, _IMAGES_QUERY, _IMAGES_QUERY)
        )
        response = requests.post(_GRAPHQL_URL, json={"query": query}, timeout=10)
        response.raise_for_status()
        results = (response.json().get("data") or {}).get("contentBySlug") or []
        if not results:
            return None, None

        item = results[0]
        original_title = item.get("originalProgramTitle") or None
        images = item.get("images") or {}
        for key in ("portrait", "wide"):
            img_id = (images.get(key) or {}).get("id")
            if img_id:
                return _IMAGE_URL.format(image_id=img_id), original_title
        return None, original_title


def _slugify(title: str) -> str:
    """Convert a show title to an SVT Play URL slug.

    SVT Play slugs are the title lowercased with diacritical marks stripped
    (å→a, ä→a, ö→o, é→e, …), spaces replaced with hyphens, and all other
    non-alphanumeric characters removed.  The NFKD normalisation handles any
    Latin-script language, not just Swedish.
    """
    normalized = unicodedata.normalize("NFKD", title.lower())
    ascii_only = "".join(c for c in normalized if not unicodedata.combining(c))
    hyphenated = re.sub(r"[\s_]+", "-", ascii_only)
    slug = re.sub(r"[^a-z0-9-]", "", hyphenated)
    return re.sub(r"-+", "-", slug).strip("-")
