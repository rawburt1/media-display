"""MediaDataStore-backed artwork enricher: checks the local unified
media-data cache (see mediainfo/media_data_store.py) for album art +
artist photo (music), or poster+fanart (movies/episodes), appending to
now_playing.images exactly like every other artwork enricher - never
replacing (that's reserved for PosterStore/ArtworkOverrideStore
downstream, see orchestrator_artwork.py). Off by default
(enrichers.mediadata.enabled: false); list it first among enrichers if
enabled, mirroring LibraryEnricher's placement, so a cache hit here
saves every enricher after it a redundant lookup.

Music checks artist photo (marked is_artist_photo=True, so PixooOutput's
music_album_art_only filter skips it) whenever an artist is known, and
album art additionally once an album is known - not fanart, since
MediaDataStore's album fanart fetch is a guaranteed no-op today (neither
MusicBrainz nor Discogs has a distinct "album background art" concept).
Movies/episodes check both poster and fanart, since TMDb provides both.

Also renders a lyrics word cloud for music, once lyrics and album art are
both cached (marked is_wordcloud=True, so only WebOutput's
show_wordclouds shows it - see orchestrator_artwork.py) - behind its own
enrichers.mediadata.wordcloud.enabled switch (config.wordcloud.enabled),
independent of this enricher's own `enabled` flag, since generation costs
real CPU time per newly-seen track.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.config import MediaDataArtworkEnricherConfig

logger = logging.getLogger(__name__)


class MediaDataArtworkEnricher(ArtworkEnricher):
    name = "mediadata"
    config_class = MediaDataArtworkEnricherConfig
    capabilities = frozenset({"mediadata"})

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
        artist = now_playing.subtitle
        if not artist:
            return

        photo = store.get_artist_photo(artist)
        self._append(now_playing, photo, "Artist photo (mediadata)", is_artist_photo=True)

        album = now_playing.album
        if not album:
            return

        path = store.get_album_art(artist, album, now_playing.year)
        self._append(now_playing, path, "Album art (mediadata)")

        title = now_playing.title
        if title and self.config.wordcloud.enabled:
            wordcloud_path = store.get_track_wordcloud(artist, album, title, now_playing.year)
            self._append(
                now_playing, wordcloud_path, "Lyrics word cloud (mediadata)", is_wordcloud=True
            )

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
    def _append(
        now_playing: NowPlaying,
        path: Optional[Path],
        label: str,
        is_artist_photo: bool = False,
        is_wordcloud: bool = False,
    ) -> None:
        if path is None:
            return
        url = f"file://{path}"
        if not any(img.url == url for img in now_playing.images):
            now_playing.images.append(
                Artwork(
                    url=url, label=label, is_artist_photo=is_artist_photo, is_wordcloud=is_wordcloud
                )
            )
