"""Local music library idle wallpaper source.

Shows cover art from random albums in the local music library (see
mediainfo.musiclibrary - populated via `python -m mediainfo import-lidarr`)
on outputs while nothing is currently playing.

Cover art URLs are cached as a library claim per album (the Cover Art
Archive lookup is otherwise a fresh network request every rotation, for
albums that get picked again and again out of a large library).
"""

from __future__ import annotations

import logging
from typing import List, Optional

from mediainfo.config import LibraryIdleConfig
from mediainfo.enrichers.musicbrainz import fetch_front_cover
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import Artwork
from mediainfo.musiclibrary import MusicLibrary

logger = logging.getLogger(__name__)


class LibraryWallpaperSource(IdleWallpaperSource):
    config_class = LibraryIdleConfig
    name = "library"
    capabilities = frozenset({"library"})

    def __init__(self, config: LibraryIdleConfig, library: Optional[MusicLibrary] = None):
        self.config = config
        self.library = library
        self.rotation_interval_seconds = config.rotation_interval_seconds

    def get_wallpapers(self) -> List[Artwork]:
        if self.library is None:
            return []

        try:
            albums = self.library.random_albums(self.config.batch_size)
        except Exception:
            logger.exception("Failed to pick random albums from the library")
            return []

        artworks = []
        for album_id, artist, title, mbid in albums:
            url = self._cover_url(self.library, album_id, mbid)
            if url:
                artworks.append(Artwork(url=url, label=f"Library: {artist} – {title}"))

        return artworks

    @staticmethod
    def _cover_url(library: MusicLibrary, album_id: int, mbid: str) -> Optional[str]:
        cached = library.get_claim("album", album_id, "cover_art_url", "musicbrainz")
        if cached is not None:
            return cached or None

        url = fetch_front_cover(mbid)
        library.set_claim("album", album_id, "cover_art_url", "musicbrainz", url or "")
        return url
