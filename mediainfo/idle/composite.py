"""Combines multiple idle wallpaper sources WITHOUT mixing them within a
single batch - each batch comes entirely from one source, never blended.

Each source is still refetched independently on its own configured
rotation_interval_seconds (its last successful result is cached and
reused between its own refetches, same as before) - what's changed from
this class' original "merge everything into one pool" behavior is the
final step: instead of combining every source's cached pictures together,
exactly one source's cached pictures are returned, chosen by `mode`:

- "priority": try sources in the given order, use the first one that has
  a non-empty cached batch.
- "random": same "exactly one source, never mixed" result, but the order
  sources are tried in is reshuffled every call, so which one wins varies
  randomly instead of always preferring the same one first.
"""

from __future__ import annotations

import random
import time
from typing import List, Optional

from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import Artwork


class CompositeIdleWallpaperSource(IdleWallpaperSource):
    def __init__(self, sources: List[IdleWallpaperSource], mode: str = "priority"):
        self.sources = sources
        self.mode = mode
        self.rotation_interval_seconds = min(s.rotation_interval_seconds for s in sources)
        # -inf, not 0.0: time.monotonic()'s zero point is unspecified (often
        # system boot on Linux) - seeding with 0.0 would skip the first
        # fetch whenever monotonic() happens to read less than a source's
        # rotation_interval_seconds (e.g. a freshly booted CI runner).
        self._last_fetch = [float("-inf")] * len(sources)
        self._cached: List[List[Artwork]] = [[] for _ in sources]
        # Whichever source's pictures were actually returned by the most
        # recent get_wallpapers() call - lets callers (see
        # mediainfo.orchestrator_idle._IdleBatchManager) apply that one
        # source's own transform_pipeline to the current batch, since
        # exactly one source's pictures make up any given batch (never
        # blended - see the module docstring).
        self.last_used: Optional[IdleWallpaperSource] = None

    def get_wallpapers(self) -> List[Artwork]:
        now = time.monotonic()
        for i, source in enumerate(self.sources):
            if now - self._last_fetch[i] >= source.rotation_interval_seconds:
                images = source.get_wallpapers()
                if images:
                    self._cached[i] = images
                self._last_fetch[i] = now

        order = list(range(len(self.sources)))
        if self.mode == "random":
            random.shuffle(order)
        for i in order:
            if self._cached[i]:
                self.last_used = self.sources[i]
                return self._cached[i]
        return []
