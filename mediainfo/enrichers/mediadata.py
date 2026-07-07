"""MediaDataStore-backed artwork enricher: checks the local unified
media-data cache (see mediainfo/media_data_store.py) for album art,
appending it to now_playing.images exactly like every other artwork
enricher - never replacing (that's reserved for PosterStore/
ArtworkOverrideStore downstream, see orchestrator_artwork.py). Off by
default (enrichers.mediadata.enabled: false); list it first among
enrichers if enabled, mirroring LibraryEnricher's placement, so a cache
hit here saves every enricher after it a redundant lookup.

Only ever acts on media_type == "music" - movie/series artwork isn't
covered yet (MediaDataStore's _fetch_movie_artwork/_fetch_series_artwork
remain stubs, see that module's docstring). Only checks album art, not
fanart - MediaDataStore's album fanart fetch is a guaranteed no-op today
(neither MusicBrainz nor Discogs has a distinct "album background art"
concept), so there's nothing to gain from also calling it.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)


class MediaDataArtworkEnricher(ArtworkEnricher):
    def __init__(self, config: Any, store: Optional[MediaDataStore] = None):
        self.config = config
        self.store = store

    def enrich(self, now_playing: NowPlaying) -> None:
        if self.store is None or now_playing.media_type != "music":
            return

        # subtitle holds the artist for music items - see NowPlaying's
        # own docstring for why (same convention every other music
        # enricher already follows).
        artist, album = now_playing.subtitle, now_playing.album
        if not artist or not album:
            return

        try:
            path = self.store.get_album_art(artist, album, now_playing.year)
            if path is None:
                return
            url = f"file://{path}"
            if not any(img.url == url for img in now_playing.images):
                now_playing.images.append(Artwork(url=url, label="Album art (mediadata)"))
        except Exception:
            logger.exception("MediaDataStore artwork enrichment error")
