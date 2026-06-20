"""Sonarr enricher: adds the producing network/studio and a poster/fanart
for TV episodes, by matching the playing show against Sonarr's own library
(the shows you actually track, rather than a public catalog).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from mediainfo.config import SonarrConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)


class SonarrEnricher(ArtworkEnricher):
    def __init__(self, config: SonarrConfig):
        self.config = config
        self._base = f"http://{config.host}:{config.port}"

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "episode":
            return

        try:
            series = self._find_series(now_playing)
            if series is None:
                return

            if series.get("network") and not now_playing.studio:
                now_playing.studio = series["network"]

            self._append_images(now_playing, series.get("images") or [])
        except Exception:
            logger.exception("Sonarr enrichment error")

    def _find_series(self, now_playing: NowPlaying) -> Optional[dict]:
        tvdb_id = now_playing.ids.get("tvdb")
        if tvdb_id:
            results = self._get("/api/v3/series", params={"tvdbId": tvdb_id})
            if results:
                return results[0]

        if not now_playing.title:
            return None
        results = self._get("/api/v3/series") or []
        title = now_playing.title.strip().casefold()
        for series in results:
            if (series.get("title") or "").strip().casefold() == title:
                return series
        return None

    @staticmethod
    def _append_images(now_playing: NowPlaying, images: list) -> None:
        for cover_type, label in (("poster", "Poster (Sonarr)"), ("fanart", "Fanart (Sonarr)")):
            url = next(
                (img.get("remoteUrl") or img.get("url")
                 for img in images if img.get("coverType") == cover_type),
                None,
            )
            if url and not any(image.url == url for image in now_playing.images):
                now_playing.images.append(Artwork(url=url, label=label))

    def _get(self, path: str, params: Optional[dict] = None) -> Optional[Any]:
        response = requests.get(
            f"{self._base}{path}",
            params=params,
            headers={"X-Api-Key": self.config.api_key},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
