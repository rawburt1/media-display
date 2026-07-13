"""MediaDataStore-backed lyrics enricher: checks the local unified
media-data cache (see mediainfo/media_data_store.py) for track lyrics,
setting NowPlaying.lyrics on a hit. Off by default
(text_enrichers.mediadata.enabled: false).

Unlike artwork enrichers (which only ever append), text enrichers each
freely set NowPlaying's text fields - whichever one runs last simply
wins, same convention every other text enricher already follows; list
this one wherever you want it to take priority relative to lrclib/etc.

Doesn't set synced_lyrics: the cached .lrc file may hold either synced
(LRC-timestamped) or plain lyrics depending on what was available when
it was first fetched (see MediaDataStore._fetch_lyrics), and there's no
reliable way to tell which format a plain string is after the fact
without re-parsing it - left as plain `lyrics` text either way, rather
than guessing.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from mediainfo.enrichers.text_base import TextEnricher
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import NowPlaying
from mediainfo.config import MediaDataLyricsEnricherConfig

logger = logging.getLogger(__name__)


class MediaDataLyricsEnricher(TextEnricher):
    name = "mediadata"
    config_class = MediaDataLyricsEnricherConfig
    capabilities = frozenset({"mediadata"})

    def __init__(self, config: Any, store: Optional[MediaDataStore] = None):
        self.config = config
        self.store = store

    def enrich(self, now_playing: NowPlaying) -> None:
        if self.store is None:
            return

        # Self-gated to once every 24h - cheap to call on every track
        # change (M2 in docs/architecture-usability-review-2026-07.md).
        # Never raises - see maybe_evict_by_size()'s own docstring.
        self.store.maybe_evict_by_size()

        if now_playing.media_type != "music":
            return

        artist, title, album = now_playing.subtitle, now_playing.title, now_playing.album
        if not artist or not title:
            return

        try:
            lyrics = self.store.get_track_lyrics(artist, album, title, now_playing.year)
            if lyrics:
                now_playing.lyrics = lyrics
        except Exception:
            logger.exception("MediaDataStore lyrics enrichment error")
