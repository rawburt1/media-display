"""fanart.tv enricher: adds posters/backgrounds for movies and TV shows."""

from __future__ import annotations

import logging
from typing import Iterable, Optional, Tuple

import requests

from pixoo_media.config import FanartTvConfig
from pixoo_media.enrichers.base import ArtworkEnricher
from pixoo_media.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)

_BASE_URL = "https://webservice.fanart.tv/v3"
_PREFERRED_LANGS = {"en", "00", ""}

_MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2/release-group/"
_MUSICBRAINZ_USER_AGENT = "pixoo-media-display/1.0 (personal use)"


class FanartTvEnricher(ArtworkEnricher):
    def __init__(self, config: FanartTvConfig):
        self.config = config

    def enrich(self, now_playing: NowPlaying) -> None:
        try:
            if now_playing.media_type == "movie":
                self._enrich_movie(now_playing)
            elif now_playing.media_type == "episode":
                self._enrich_tv(now_playing)
            elif now_playing.media_type == "music":
                self._enrich_music(now_playing)
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

    def _enrich_music(self, now_playing: NowPlaying) -> None:
        artist_id = now_playing.ids.get("musicbrainzartist")
        album_id = now_playing.ids.get("musicbrainzalbum")

        if not artist_id or not album_id:
            resolved = self._resolve_musicbrainz_ids(now_playing.subtitle, now_playing.album)
            if resolved is None:
                return
            artist_id, album_id = resolved

        data = self._get(f"music/{artist_id}")
        if not data:
            return

        album = (data.get("albums") or {}).get(album_id)
        if not album:
            return

        # Prefer fanart.tv's album cover over the source's own album art by
        # putting it first in the rotation.
        self._prepend_best(now_playing, album.get("albumcover"), "Album (fanart.tv)")

    @staticmethod
    def _resolve_musicbrainz_ids(artist: str, album: str) -> Optional[Tuple[str, str]]:
        """Look up an artist + album's MusicBrainz ids by name, for sources
        (e.g. Sonos) that don't expose MusicBrainz ids directly.
        """
        if not artist or not album:
            return None

        query = f'artist:"{artist}" AND release:"{album}"'
        try:
            response = requests.get(
                _MUSICBRAINZ_URL,
                params={"query": query, "fmt": "json", "limit": 5},
                headers={"User-Agent": _MUSICBRAINZ_USER_AGENT},
                timeout=10,
            )
            response.raise_for_status()
            groups = response.json().get("release-groups") or []
        except Exception:
            logger.exception("MusicBrainz lookup failed for %r - %r", artist, album)
            return None

        if not groups:
            return None

        # Prefer an actual studio album over compilations/live recordings/etc.
        group = next((g for g in groups if g.get("primary-type") == "Album"), groups[0])
        artist_credit = group.get("artist-credit") or []
        if not artist_credit:
            return None

        return artist_credit[0]["artist"]["id"], group["id"]

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
    def _best_url(entries: Optional[Iterable[dict]]) -> Optional[str]:
        entries = list(entries or [])
        if not entries:
            return None

        preferred = [entry for entry in entries if entry.get("lang") in _PREFERRED_LANGS]
        candidates = preferred or entries
        best = max(candidates, key=lambda entry: int(entry.get("likes") or 0))
        return best.get("url")

    @classmethod
    def _append_best(
        cls, now_playing: NowPlaying, entries: Optional[Iterable[dict]], label: str
    ) -> None:
        url = cls._best_url(entries)
        if url and not any(image.url == url for image in now_playing.images):
            now_playing.images.append(Artwork(url=url, label=label))

    @classmethod
    def _prepend_best(
        cls, now_playing: NowPlaying, entries: Optional[Iterable[dict]], label: str
    ) -> None:
        url = cls._best_url(entries)
        if url and not any(image.url == url for image in now_playing.images):
            now_playing.images.insert(0, Artwork(url=url, label=label))
