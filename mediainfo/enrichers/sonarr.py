"""Sonarr enricher: adds the producing network/studio and a poster/fanart
for TV episodes, by matching the playing show against Sonarr's own library
(the shows you actually track, rather than a public catalog).
"""

from __future__ import annotations

import logging
from typing import Optional

from mediainfo.config import SonarrConfig
from mediainfo.enrichers.arr_base import ArrEnricher
from mediainfo.models import NowPlaying

logger = logging.getLogger(__name__)


class SonarrEnricher(ArrEnricher):
    def __init__(self, config: SonarrConfig):
        super().__init__(config)

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "episode":
            return

        try:
            series = self._find_series(now_playing)
            if series is None:
                return

            if series.get("network") and not now_playing.studio:
                now_playing.studio = series["network"]

            images = series.get("images") or []
            self._append_image(now_playing, images, "poster", "Poster (Sonarr)")
            self._append_image(now_playing, images, "fanart", "Fanart (Sonarr)")
        except Exception:
            logger.exception("Sonarr enrichment error")

    def _find_series(self, now_playing: NowPlaying) -> Optional[dict]:
        tvdb_id = now_playing.ids.get("tvdb")
        if tvdb_id:
            results = self._get("/api/v3/series", params={"tvdbId": tvdb_id})
            if results:
                return results[0]

        results = self._get("/api/v3/series") or []
        return self._find_by_exact_title(results, now_playing.title, "title")
