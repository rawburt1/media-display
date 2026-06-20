"""Radarr enricher: adds the producing studio, genres, and a poster/fanart
for movies, by matching the playing title against Radarr's own library
(the movies you actually track, rather than a public catalog).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from mediainfo.config import RadarrConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)


class RadarrEnricher(ArtworkEnricher):
    def __init__(self, config: RadarrConfig):
        self.config = config
        self._base = f"http://{config.host}:{config.port}"

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

            self._append_images(now_playing, movie.get("images") or [])
        except Exception:
            logger.exception("Radarr enrichment error")

    def _find_movie(self, now_playing: NowPlaying) -> Optional[dict]:
        tmdb_id = now_playing.ids.get("tmdb")
        if tmdb_id:
            results = self._get("/api/v3/movie", params={"tmdbId": tmdb_id})
            if results:
                return results[0]

        if not now_playing.title:
            return None
        results = self._get("/api/v3/movie") or []
        title = now_playing.title.strip().casefold()
        for movie in results:
            if (movie.get("title") or "").strip().casefold() == title:
                return movie
        return None

    @staticmethod
    def _append_images(now_playing: NowPlaying, images: list) -> None:
        for cover_type, label in (("poster", "Poster (Radarr)"), ("fanart", "Fanart (Radarr)")):
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
