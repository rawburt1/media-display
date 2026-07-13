"""fanart.tv enricher: adds posters/backgrounds for movies and TV shows."""

from __future__ import annotations

import logging
from typing import Iterable, Optional, Tuple

import requests

from mediainfo.config import FanartTvConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.enrichers.musicbrainz import resolve_release_group_ids
from mediainfo.models import Artwork, NowPlaying
from mediainfo.musiclibrary import MusicLibrary

logger = logging.getLogger(__name__)

_BASE_URL = "https://webservice.fanart.tv/v3"
_PREFERRED_LANGS = {"en", "00", ""}


def fetch(api_key: str, path: str) -> Optional[dict]:
    try:
        response = requests.get(f"{_BASE_URL}/{path}", params={"api_key": api_key}, timeout=10)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except Exception:
        logger.exception("fanart.tv request failed for %s", path)
        return None


def best_url(entries: Optional[Iterable[dict]]) -> Optional[str]:
    entries = list(entries or [])
    if not entries:
        return None

    preferred = [entry for entry in entries if entry.get("lang") in _PREFERRED_LANGS]
    candidates = preferred or entries
    best = max(candidates, key=lambda entry: int(entry.get("likes") or 0))
    return best.get("url")


class FanartTvEnricher(ArtworkEnricher):
    name = "fanarttv"
    config_class = FanartTvConfig
    capabilities = frozenset({"library"})

    def __init__(self, config: FanartTvConfig, library: Optional[MusicLibrary] = None):
        self.config = config
        self.library = library

    def test_connection(self) -> Tuple[bool, str]:
        try:
            # 603 is The Matrix's TMDb id - a stable, well-known test
            # target for fanart.tv's movie lookup.
            data = self._get("movies/603")
            if data is not None:
                return True, "API reachable"
            return False, "No response - check api_key"
        except Exception as exc:
            return False, f"Error: {exc}"

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
            entry for entry in season_posters if str(entry.get("season")) == str(now_playing.season)
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
            resolved = resolve_release_group_ids(
                self.library, now_playing.subtitle, now_playing.album
            )
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

    def _get(self, path: str) -> Optional[dict]:
        return fetch(self.config.api_key, path)

    @staticmethod
    def _best_url(entries: Optional[Iterable[dict]]) -> Optional[str]:
        return best_url(entries)

    @classmethod
    def _append_best(
        cls, now_playing: NowPlaying, entries: Optional[Iterable[dict]], label: str
    ) -> None:
        url = best_url(entries)
        if url and not any(image.url == url for image in now_playing.images):
            now_playing.images.append(Artwork(url=url, label=label))

    @classmethod
    def _prepend_best(
        cls, now_playing: NowPlaying, entries: Optional[Iterable[dict]], label: str
    ) -> None:
        url = best_url(entries)
        if url and not any(image.url == url for image in now_playing.images):
            now_playing.images.insert(0, Artwork(url=url, label=label))
