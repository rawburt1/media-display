"""SVT Play enricher: fetches show poster art from SVT's content API and
optionally resolves the tvdb-id via Sonarr.

Fills in artwork for episodes detected from the SVT Play app when no
other enricher has found any - derives a URL slug from the Swedish title
and queries SVT's internal GraphQL API (contento.svt.se/graphql). No API
key or account required; uses a public endpoint.

This covers the common case of SVT shows that are titled in Swedish and
therefore not findable by thetvdb.com's search API (which only indexes
shows by their original-language or English name).

When a Sonarr host is configured, the enricher also queries Sonarr's
series library to match the Swedish title against each series' main title
and its alternate titles - this fills in `ids["tvdb"]` on the NowPlaying
object so enrichers like thetvdb and fanarttv can subsequently fetch
proper artwork using the id rather than a title search.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

import requests

from mediainfo.config import SvtConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)

_GRAPHQL_URL = "https://contento.svt.se/graphql"
_IMAGE_URL = "https://www.svtstatic.se/image/medium/960/{image_id}"

_IMAGES_QUERY = "images { portrait { id } wide { id } }"


class SvtEnricher(ArtworkEnricher):
    def __init__(self, config: SvtConfig):
        self.config = config
        # title -> image URL (or None for "not found"), cached per process run
        self._cache: dict[str, Optional[str]] = {}
        self._sonarr_enabled = bool(config.sonarr_host and config.sonarr_api_key)
        # None means "not yet fetched"; a list (possibly empty) means fetched
        self._sonarr_series_cache: Optional[list] = None

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

        if now_playing.images:
            return  # another enricher already found artwork

        try:
            image_url = self._resolve(now_playing.title)
            if image_url:
                now_playing.images.append(Artwork(url=image_url, label="Poster (SVT)"))
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
        if self._sonarr_series_cache is not None:
            return self._sonarr_series_cache
        url = f"http://{self.config.sonarr_host}:{self.config.sonarr_port}/api/v3/series"
        response = requests.get(
            url,
            headers={"X-Api-Key": self.config.sonarr_api_key},
            timeout=10,
        )
        response.raise_for_status()
        self._sonarr_series_cache = response.json()
        return self._sonarr_series_cache

    # ------------------------------------------------------------------
    # SVT GraphQL artwork lookup
    # ------------------------------------------------------------------

    def _resolve(self, title: str) -> Optional[str]:
        if title in self._cache:
            return self._cache[title]

        slug = _slugify(title)
        image_url = self._fetch(slug)
        if image_url:
            logger.info("SVT: found artwork for %r (slug %r)", title, slug)
        else:
            logger.debug("SVT: no match for %r (slug %r)", title, slug)
        self._cache[title] = image_url
        return image_url

    def _fetch(self, slug: str) -> Optional[str]:
        query = (
            '{ contentBySlug(slugs: ["%s"]) {'
            ' ... on TvSeries { %s }'
            ' ... on SingleVideo { %s }'
            '} }' % (slug, _IMAGES_QUERY, _IMAGES_QUERY)
        )
        response = requests.post(_GRAPHQL_URL, json={"query": query}, timeout=10)
        response.raise_for_status()
        results = (response.json().get("data") or {}).get("contentBySlug") or []
        if not results:
            return None

        images = results[0].get("images") or {}
        for key in ("portrait", "wide"):
            img_id = (images.get(key) or {}).get("id")
            if img_id:
                return _IMAGE_URL.format(image_id=img_id)
        return None


def _slugify(title: str) -> str:
    """Convert a Swedish show title to an SVT Play URL slug.

    SVT Play slugs are the show's Swedish title lowercased, with Swedish
    characters (å, ä, ö) transliterated to their ASCII equivalents, spaces
    replaced with hyphens, and all other non-alphanumeric characters removed.
    """
    # Decompose accented characters (å→a+combining-ring, ä→a+combining-diaeresis…)
    normalized = unicodedata.normalize("NFKD", title.lower())
    # Drop the combining diacritical marks, keeping only the base letters
    ascii_only = "".join(c for c in normalized if not unicodedata.combining(c))
    hyphenated = re.sub(r"[\s_]+", "-", ascii_only)
    slug = re.sub(r"[^a-z0-9-]", "", hyphenated)
    return re.sub(r"-+", "-", slug).strip("-")
