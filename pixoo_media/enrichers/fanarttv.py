"""fanart.tv enricher: adds posters/backgrounds for movies and TV shows."""

from __future__ import annotations

import logging
from typing import Iterable, Optional

import requests

from pixoo_media.config import FanartTvConfig
from pixoo_media.enrichers.base import ArtworkEnricher
from pixoo_media.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)

_BASE_URL = "https://webservice.fanart.tv/v3"
_PREFERRED_LANGS = {"en", "00", ""}


class FanartTvEnricher(ArtworkEnricher):
    def __init__(self, config: FanartTvConfig):
        self.config = config

    def enrich(self, now_playing: NowPlaying) -> None:
        try:
            if now_playing.media_type == "movie":
                self._enrich_movie(now_playing)
            elif now_playing.media_type == "episode":
                self._enrich_tv(now_playing)
        except Exception:
            logger.exception("fanart.tv enrichment error")

    def _enrich_movie(self, now_playing: NowPlaying) -> None:
        movie_id = now_playing.ids.get("tmdb") or now_playing.ids.get("imdb")
        if not movie_id:
            return

        data = self._get(f"movies/{movie_id}")
        if not data:
            return

        self._append_best(now_playing, data.get("movieposter"), "Poster (fanart.tv)")
        self._append_best(now_playing, data.get("moviebackground"), "Fanart (fanart.tv)")

    def _enrich_tv(self, now_playing: NowPlaying) -> None:
        show_id = now_playing.ids.get("tvdb")
        if not show_id:
            return

        data = self._get(f"tv/{show_id}")
        if not data:
            return

        season_posters = data.get("seasonposter") or []
        season_match = [
            entry
            for entry in season_posters
            if str(entry.get("season")) == str(now_playing.season)
        ]
        if season_match:
            self._append_best(now_playing, season_match, "Season poster (fanart.tv)")
        else:
            self._append_best(now_playing, data.get("tvposter"), "Poster (fanart.tv)")

        self._append_best(now_playing, data.get("showbackground"), "Fanart (fanart.tv)")

    def _get(self, path: str) -> Optional[dict]:
        try:
            response = requests.get(
                f"{_BASE_URL}/{path}", params={"api_key": self.config.api_key}, timeout=10
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except Exception:
            logger.exception("fanart.tv request failed for %s", path)
            return None

    @staticmethod
    def _append_best(
        now_playing: NowPlaying, entries: Optional[Iterable[dict]], label: str
    ) -> None:
        entries = list(entries or [])
        if not entries:
            return

        preferred = [entry for entry in entries if entry.get("lang") in _PREFERRED_LANGS]
        candidates = preferred or entries
        best = max(candidates, key=lambda entry: int(entry.get("likes") or 0))

        url = best.get("url")
        if url and not any(image.url == url for image in now_playing.images):
            now_playing.images.append(Artwork(url=url, label=label))
