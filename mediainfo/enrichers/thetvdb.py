"""thetvdb.com enricher: adds posters/backgrounds for TV shows.

Most sources (Kodi, Jellyfin/Emby, Plex) already supply a tvdb series id
from their own local library metadata. Sources that can't (e.g. the
Shield source, which only knows a title parsed from a generic Android
media session - see sources/shield.py) get a title-based fallback here:
thetvdb.com's own search API resolves a series name to its id, cached in
memory for the life of the process (same trade-off as the Wikipedia
enricher's cache - no persistence, but a given title is only looked up
once per run). The resolved id is written back into `now_playing.ids`,
so the fanart.tv enricher's TV branch (which also needs a tvdb id) gets
to use it too, if it runs afterward.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from mediainfo.config import TheTvDbConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)

_BASE_URL = "https://api4.thetvdb.com/v4"


class TheTvDbEnricher(ArtworkEnricher):
    def __init__(self, config: TheTvDbConfig):
        self.config = config
        self._token: Optional[str] = None
        # Artwork "type" ids for series posters/backgrounds, discovered from
        # /artwork/types on first use (these ids are not documented as fixed
        # constants, so look them up by name instead of hardcoding them).
        self._poster_type: Optional[int] = None
        self._background_type: Optional[int] = None
        # Title -> resolved series id (or None for "not found"), for
        # sources that only give us a name - see module docstring.
        self._series_search_cache: dict[str, Optional[str]] = {}

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "episode":
            return

        try:
            series_id = now_playing.ids.get("tvdb")
            if not series_id:
                if not now_playing.title:
                    return
                series_id = self._resolve_series_id(now_playing.title)
                if not series_id:
                    return
                now_playing.ids["tvdb"] = series_id

            if not self._ensure_artwork_types():
                return

            data = self._get(f"/series/{series_id}/artworks", params={"lang": "eng"})
            if not data:
                return

            artworks = data.get("artworks") or []
            self._append_best(now_playing, artworks, self._poster_type, "Poster (TheTVDB)")
            self._append_best(now_playing, artworks, self._background_type, "Fanart (TheTVDB)")
        except Exception:
            logger.exception("thetvdb.com enrichment error")

    def _resolve_series_id(self, title: str) -> Optional[str]:
        if title in self._series_search_cache:
            return self._series_search_cache[title]

        series_id = None
        results = self._get("/search", params={"query": title, "type": "series"})
        for result in results or []:
            candidate = result.get("tvdb_id")
            if candidate:
                series_id = str(candidate)
                break

        self._series_search_cache[title] = series_id
        return series_id

    def _ensure_artwork_types(self) -> bool:
        if self._poster_type is not None and self._background_type is not None:
            return True

        types = self._get("/artwork/types")
        if not types:
            return False

        for entry in types:
            if entry.get("recordType") != "series":
                continue
            name = (entry.get("name") or "").strip().lower()
            if name == "poster":
                self._poster_type = entry.get("id")
            elif name in ("background", "fanart"):
                self._background_type = entry.get("id")

        return self._poster_type is not None and self._background_type is not None

    def _login(self) -> Optional[str]:
        payload: dict[str, str] = {"apikey": self.config.api_key}
        if self.config.pin:
            payload["pin"] = self.config.pin

        try:
            response = requests.post(f"{_BASE_URL}/login", json=payload, timeout=10)
            response.raise_for_status()
            return response.json().get("data", {}).get("token")
        except Exception:
            logger.exception("thetvdb.com login failed")
            return None

    def _get(self, path: str, params: Optional[dict] = None) -> Optional[Any]:
        if self._token is None:
            self._token = self._login()
            if self._token is None:
                return None

        url = f"{_BASE_URL}{path}"
        response = requests.get(
            url, headers={"Authorization": f"Bearer {self._token}"}, params=params, timeout=10
        )

        if response.status_code == 401:
            # Token likely expired (tokens last ~1 month); re-login once and retry.
            self._token = self._login()
            if self._token is None:
                return None
            response = requests.get(
                url, headers={"Authorization": f"Bearer {self._token}"}, params=params, timeout=10
            )

        if response.status_code == 404:
            return None

        response.raise_for_status()
        return response.json().get("data")

    @staticmethod
    def _append_best(
        now_playing: NowPlaying, artworks: list, artwork_type: Optional[int], label: str
    ) -> None:
        if artwork_type is None:
            return

        candidates = [a for a in artworks if a.get("type") == artwork_type]
        if not candidates:
            return

        best = max(candidates, key=lambda entry: entry.get("score") or 0)
        url = best.get("image")
        if url and not any(image.url == url for image in now_playing.images):
            now_playing.images.append(Artwork(url=url, label=label))
