"""Merges multiple idle wallpaper sources into a single pool."""

from __future__ import annotations

import time
from typing import List

from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import Artwork


class CompositeIdleWallpaperSource(IdleWallpaperSource):
    """Combines wallpapers from several sources (e.g. Unsplash + Last.fm)
    into one pool, refetching each source on its own configured
    rotation_interval_seconds rather than forcing them onto a shared one.
    """

    def __init__(self, sources: List[IdleWallpaperSource]):
        self.sources = sources
        self.rotation_interval_seconds = min(s.rotation_interval_seconds for s in sources)
        self._last_fetch = [0.0] * len(sources)
        self._cached: List[List[Artwork]] = [[] for _ in sources]

    def get_wallpapers(self) -> List[Artwork]:
        now = time.monotonic()
        combined: List[Artwork] = []
        for i, source in enumerate(self.sources):
            if now - self._last_fetch[i] >= source.rotation_interval_seconds:
                images = source.get_wallpapers()
                if images:
                    self._cached[i] = images
                self._last_fetch[i] = now
            combined.extend(self._cached[i])
        return combined
