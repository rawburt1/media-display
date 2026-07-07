"""MediaDataStore-backed artwork enricher: checks the local unified
media-data cache (see mediainfo/media_data_store.py) for album art
(music), or poster+fanart (movies/episodes), appending to
now_playing.images exactly like every other artwork enricher - never
replacing (that's reserved for PosterStore/ArtworkOverrideStore
downstream, see orchestrator_artwork.py). Off by default
(enrichers.mediadata.enabled: false); list it first among enrichers if
enabled, mirroring LibraryEnricher's placement, so a cache hit here
saves every enricher after it a redundant lookup.

Music only checks album art, not fanart - MediaDataStore's album fanart
fetch is a guaranteed no-op today (neither MusicBrainz nor Discogs has a
distinct "album background art" concept), so there's nothing to gain
from also calling it. Movies/episodes check both poster and fanart,
since TMDb provides both.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)


class MediaDataArtworkEnricher(ArtworkEnricher):
    def __init__(self, config: Any, store: Optional[MediaDataStore] = None):
        self.config = config
        self.store = store

    def enrich(self, now_playing: NowPlaying) -> None:
        store = self.store
        if store is None:
            return

        try:
            if now_playing.media_type == "music":
                self._enrich_music(now_playing, store)
            elif now_playing.media_type == "movie":
                self._enrich_media(now_playing, store.get_movie_poster, store.get_movie_fanart)
            elif now_playing.media_type == "episode":
                # title holds the show name for episodes (subtitle holds
                # the episode title/info) - see e.g. jellyfin.py's
                # SeriesName mapping.
                self._enrich_media(now_playing, store.get_series_poster, store.get_series_fanart)
        except Exception:
            logger.exception("MediaDataStore artwork enrichment error")

    def _enrich_music(self, now_playing: NowPlaying, store: MediaDataStore) -> None:
        # subtitle holds the artist for music items - see NowPlaying's
        # own docstring for why (same convention every other music
        # enricher already follows).
        artist, album = now_playing.subtitle, now_playing.album
        if not artist or not album:
            return

        path = store.get_album_art(artist, album, now_playing.year)
        self._append(now_playing, path, "Album art (mediadata)")

    def _enrich_media(
        self,
        now_playing: NowPlaying,
        get_poster: Callable[[str, Optional[int]], Optional[Path]],
        get_fanart: Callable[[str, Optional[int]], Optional[Path]],
    ) -> None:
        """Shared by movies and episodes - both look up poster+fanart the
        same way, keyed by (title, year)."""
        if not now_playing.title:
            return
        poster = get_poster(now_playing.title, now_playing.year)
        self._append(now_playing, poster, "Poster (mediadata)")
        fanart = get_fanart(now_playing.title, now_playing.year)
        self._append(now_playing, fanart, "Fanart (mediadata)")

    @staticmethod
    def _append(now_playing: NowPlaying, path: Optional[Path], label: str) -> None:
        if path is None:
            return
        url = f"file://{path}"
        if not any(img.url == url for img in now_playing.images):
            now_playing.images.append(Artwork(url=url, label=label))
