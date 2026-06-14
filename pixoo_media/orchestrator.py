"""Polling loop: picks the highest-priority active source, enriches it with
extra artwork, and rotates through the available images on enabled outputs.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import List, Optional

from pixoo_media.cache import ImageCache
from pixoo_media.enrichers.base import ArtworkEnricher
from pixoo_media.models import NowPlaying
from pixoo_media.outputs.base import Output
from pixoo_media.sources.base import MediaSource

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        sources: List[MediaSource],
        enrichers: List[ArtworkEnricher],
        outputs: List[Output],
        cache: ImageCache,
        poll_interval_seconds: float,
        rotation_interval_seconds: float,
    ):
        self.sources = sources
        self.enrichers = enrichers
        self.outputs = outputs
        self.cache = cache
        self.poll_interval_seconds = poll_interval_seconds
        self.rotation_interval_seconds = rotation_interval_seconds
        self._current: Optional[NowPlaying] = None
        self._image_index = 0
        self._last_rotation = 0.0
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def join(self) -> None:
        self._thread.join()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("Unexpected error in orchestrator loop")
            self._stop_event.wait(self.poll_interval_seconds)

    def _tick(self) -> None:
        now_playing = self._poll_sources()

        if now_playing is None:
            if self._current is not None:
                logger.info("Nothing playing; switching outputs to idle")
                for output in self.outputs:
                    self._safe_call(output.on_idle)
            self._current = None
            self._image_index = 0
            return

        if self._current is not None and now_playing.identity == self._current.identity:
            self._maybe_rotate()
            return

        for enricher in self.enrichers:
            self._safe_call(enricher.enrich, now_playing)

        logger.info(
            "Now playing changed: [%s] %s - %s (%d image(s))",
            now_playing.source,
            now_playing.title,
            now_playing.subtitle,
            len(now_playing.images),
        )

        self._current = now_playing
        self._image_index = 0
        self._last_rotation = time.monotonic()

        if not now_playing.images:
            logger.warning("No artwork available for %s", now_playing.title)
            return

        self._show_current_image()

    def _maybe_rotate(self) -> None:
        if self._current is None or len(self._current.images) <= 1:
            return

        now = time.monotonic()
        if now - self._last_rotation < self.rotation_interval_seconds:
            return

        self._image_index = (self._image_index + 1) % len(self._current.images)
        self._last_rotation = now
        self._show_current_image()

    def _show_current_image(self) -> None:
        artwork = self._current.images[self._image_index]
        try:
            image_path = self.cache.get_path(artwork)
        except Exception:
            logger.exception("Failed to fetch artwork %s", artwork.url)
            return

        if image_path is None:
            return

        for output in self.outputs:
            self._safe_call(output.update, self._current, artwork, image_path)

    def _poll_sources(self) -> Optional[NowPlaying]:
        for source in self.sources:
            now_playing = source.get_now_playing()
            if now_playing is not None:
                return now_playing
        return None

    @staticmethod
    def _safe_call(func, *args) -> None:
        try:
            func(*args)
        except Exception:
            logger.exception("Output error in %s", func)
