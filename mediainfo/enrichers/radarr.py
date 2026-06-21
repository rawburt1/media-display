"""Radarr enricher: adds the producing studio, genres, and a poster/fanart
for movies, by matching the playing title against Radarr's own library
(the movies you actually track, rather than a public catalog).
"""

from __future__ import annotations

import logging
from typing import Optional

from mediainfo.config import RadarrConfig
from mediainfo.enrichers.arr_base import ArrEnricher
from mediainfo.models import NowPlaying

logger = logging.getLogger(__name__)


class RadarrEnricher(ArrEnricher):
    def __init__(self, config: RadarrConfig):
        super().__init__(config)

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "movie":
            return

        try:
            movie = self._find_movie(now_playing)
            if movie is None:
                return

            if movie.get("studio") and not now_playing.studio:
                now_playing.studio = movie["studio"]
            if movie.get("genres") and not now_playing.genres:
                now_playing.genres = list(movie["genres"])

            images = movie.get("images") or []
            self._append_image(now_playing, images, "poster", "Poster (Radarr)")
            self._append_image(now_playing, images, "fanart", "Fanart (Radarr)")
        except Exception:
            logger.exception("Radarr enrichment error")

    def _find_movie(self, now_playing: NowPlaying) -> Optional[dict]:
        tmdb_id = now_playing.ids.get("tmdb")
        if tmdb_id:
            results = self._get("/api/v3/movie", params={"tmdbId": tmdb_id})
            if results:
                return results[0]

        results = self._get("/api/v3/movie") or []
        return self._find_by_exact_title(results, now_playing.title, "title")
