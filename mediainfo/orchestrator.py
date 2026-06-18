"""Polling loop: picks the highest-priority active source, enriches it with
extra artwork, and rotates through the available images on enabled outputs.
"""

from __future__ import annotations

import dataclasses
import logging
import random
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from mediainfo.cache import ImageCache
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

_CACHE_PURGE_INTERVAL_SECONDS = 24 * 60 * 60

# Backoff for sources whose device/service couldn't be reached (see
# MediaSource.last_poll_failed) - doubles after each consecutive failure,
# capped at _BACKOFF_MAX_SECONDS, and resets the moment a poll succeeds
# (connects fine, whether or not anything's playing). Sources that are
# simply idle - no error, nothing playing - are polled every tick as usual;
# only unreachable ones get backed off, so detection isn't delayed for
# devices that are just sitting there idle but reachable.
_BACKOFF_INITIAL_SECONDS = 30
_BACKOFF_MAX_SECONDS = 300
_BACKOFF_MULTIPLIER = 2


@dataclasses.dataclass
class _RotationState:
    """An output's independent position in a randomized cycle through
    `NowPlaying.images`."""

    order: List[int]
    position: int
    last_rotation: float


@dataclasses.dataclass
class _BackoffState:
    delay: float
    next_attempt: float


class Orchestrator:
    def __init__(
        self,
        sources: List[MediaSource],
        enrichers: List[ArtworkEnricher],
        outputs: List[Output],
        cache: ImageCache,
        poll_interval_seconds: float,
        rotation_interval_seconds: float,
        idle_source: Optional[IdleWallpaperSource] = None,
    ):
        self.sources = sources
        self.enrichers = enrichers
        self.outputs = outputs
        self.cache = cache
        self.poll_interval_seconds = poll_interval_seconds
        self.rotation_interval_seconds = rotation_interval_seconds
        self.idle_source = idle_source
        self._current: Optional[NowPlaying] = None
        # Each output independently cycles through `self._current.images` in
        # its own randomized order, keyed by its index in `self.outputs`.
        self._rotation_state: Dict[int, _RotationState] = {}
        # Same idea, but for the batch of idle wallpapers in `_idle_images`.
        self._idle_images: List[Artwork] = []
        self._idle_rotation_state: Dict[int, _RotationState] = {}
        self._idle_now_playing: Optional[NowPlaying] = None
        self._last_idle_batch_fetch = 0.0
        self._last_cache_purge: Optional[float] = None
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        # Health tracking
        self._start_time = time.monotonic()
        self._active_source_name: Optional[str] = None
        self._source_polled: Dict[str, float] = {}
        self._source_backoff: Dict[str, _BackoffState] = {}
        self._output_errors: Dict[int, Tuple[str, float]] = {}

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
        self._maybe_purge_cache()

        now_playing = self._poll_sources()

        if now_playing is None:
            if self._current is not None:
                logger.info("Nothing playing; switching outputs to idle")
                self._current = None
                self._rotation_state = {}
            self._show_idle_wallpaper()
            return

        # Clear idle state only when real artwork is available again.
        if now_playing.images and self._idle_images:
            self._idle_images = []
            self._idle_rotation_state = {}
            self._last_idle_batch_fetch = 0.0

        if self._current is not None and now_playing.identity == self._current.identity:
            if self._current.images:
                self._maybe_rotate()
            else:
                # Same no-artwork item: keep idle wallpapers running on image
                # outputs without notifying text-only outputs to go idle.
                self._show_idle_wallpaper(notify_idle=False)
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

        for index, output in enumerate(self.outputs):
            self._call_output(index, output.on_new_item, now_playing, self.cache)

        if not now_playing.images:
            logger.warning("No artwork available for %s", now_playing.title)
            self._rotation_state = {}
            self._show_idle_wallpaper(notify_idle=False)
            return

        self._rotation_state = self._build_rotation_states(
            len(now_playing.images), len(self.outputs)
        )
        for index, output in enumerate(self.outputs):
            self._show_image_for_output(index, output)

    def _maybe_purge_cache(self) -> None:
        now = time.monotonic()
        if (
            self._last_cache_purge is not None
            and now - self._last_cache_purge < _CACHE_PURGE_INTERVAL_SECONDS
        ):
            return

        self._last_cache_purge = now
        self._safe_call(self.cache.purge_expired)

    def _build_rotation_states(self, num_images: int, num_outputs: int) -> Dict[int, _RotationState]:
        """Build one _RotationState per output, sharing a single shuffled
        order but starting each output at a different position in it - so
        outputs never start on the same picture (as long as there are at
        least as many images as outputs) instead of leaving that to chance
        via independent per-output shuffles, which can (and visibly does,
        with a modest-sized image pool) coincidentally collide.

        Each output's rotation clock is also given its own random phase
        within the interval, so they don't all advance to their next image
        at the same instant either - otherwise every output would become
        "due" to rotate on the exact same tick forever after.
        """
        order = list(range(num_images))
        random.shuffle(order)
        now = time.monotonic()
        states = {}
        for index in range(num_outputs):
            jitter = random.uniform(0, self.rotation_interval_seconds)
            states[index] = _RotationState(
                order=order, position=index % num_images, last_rotation=now - jitter
            )
        return states

    def _maybe_rotate(self) -> None:
        if self._current is None or len(self._current.images) <= 1:
            return

        now = time.monotonic()
        for index, output in enumerate(self.outputs):
            state = self._rotation_state.get(index)
            if state is None or now - state.last_rotation < self.rotation_interval_seconds:
                continue

            state.position = (state.position + 1) % len(state.order)
            state.last_rotation = now
            self._show_image_for_output(index, output)

    def _show_image_for_output(self, index: int, output: Output) -> None:
        state = self._rotation_state[index]
        artwork = self._current.images[state.order[state.position]]
        try:
            image_path = self.cache.get_path(artwork)
            if image_path is None:
                return
            image_path = self.cache.get_transformed_path(image_path, output.transform_pipeline)
        except Exception:
            logger.exception("Failed to fetch artwork %s", artwork.url)
            return

        self._call_output(index, output.update, self._current, artwork, image_path)

    def _show_idle_wallpaper(self, notify_idle: bool = True) -> None:
        """Show idle wallpapers on image-capable outputs.

        notify_idle controls whether on_idle() is called (set to False when
        something is playing but has no artwork, so outputs keep their current
        display instead of clearing).
        """
        # Non-image outputs (e.g. Ulanzi text, video player) always manage
        # their own idle display; notify them regardless of idle_source.
        if notify_idle:
            for i, output in enumerate(self.outputs):
                if not output.handles_images:
                    self._call_output(i, output.on_idle)

        if self.idle_source is None:
            if notify_idle:
                for i, output in enumerate(self.outputs):
                    if output.handles_images:
                        self._call_output(i, output.on_idle)
            return

        now = time.monotonic()
        if (
            not self._idle_images
            or now - self._last_idle_batch_fetch >= self.idle_source.rotation_interval_seconds
        ):
            images = self.idle_source.get_wallpapers()
            if not images:
                if not self._idle_images and notify_idle:
                    for i, output in enumerate(self.outputs):
                        if output.handles_images:
                            self._call_output(i, output.on_idle)
                return

            logger.info("Fetched %d idle wallpaper(s)", len(images))
            self._idle_images = images
            self._idle_now_playing = NowPlaying(
                source="idle", media_type="wallpaper", title="", subtitle="", images=images
            )
            self._last_idle_batch_fetch = now
            self._idle_rotation_state = self._build_rotation_states(len(images), len(self.outputs))
            for index, output in enumerate(self.outputs):
                self._show_idle_image_for_output(index, output)
            return

        if len(self._idle_images) <= 1:
            return

        for index, output in enumerate(self.outputs):
            state = self._idle_rotation_state.get(index)
            if state is None or now - state.last_rotation < self.rotation_interval_seconds:
                continue

            state.position = (state.position + 1) % len(state.order)
            state.last_rotation = now
            self._show_idle_image_for_output(index, output)

    def _show_idle_image_for_output(self, index: int, output: Output) -> None:
        if not output.handles_images:
            return
        state = self._idle_rotation_state[index]
        artwork = self._idle_images[state.order[state.position]]
        try:
            image_path = self.cache.get_path(artwork, idle=True)
            if image_path is None:
                return
            image_path = self.cache.get_transformed_path(image_path, output.transform_pipeline)
        except Exception:
            logger.exception("Failed to fetch idle wallpaper %s", artwork.url)
            return

        logger.info("Idle wallpaper: %s", artwork.label)
        self._call_output(index, output.update, self._idle_now_playing, artwork, image_path)

    def _poll_sources(self) -> Optional[NowPlaying]:
        now = time.monotonic()
        for source in self.sources:
            name = getattr(source, "name", type(source).__name__)

            backoff = self._source_backoff.get(name)
            if backoff is not None and now < backoff.next_attempt:
                continue  # backing off: skip polling this source this tick

            self._source_polled[name] = now
            result = source.get_now_playing()

            if getattr(source, "last_poll_failed", False):
                self._source_backoff[name] = self._next_backoff(backoff, now)
            elif backoff is not None:
                del self._source_backoff[name]

            if result is not None:
                self._active_source_name = name
                return result
        self._active_source_name = None
        return None

    @staticmethod
    def _next_backoff(previous: Optional["_BackoffState"], now: float) -> "_BackoffState":
        if previous is None:
            delay = _BACKOFF_INITIAL_SECONDS
        else:
            delay = min(previous.delay * _BACKOFF_MULTIPLIER, _BACKOFF_MAX_SECONDS)
        return _BackoffState(delay=delay, next_attempt=now + delay)

    def _call_output(self, index: int, func, *args) -> None:
        """Call an output method, recording any exception for health reporting."""
        try:
            func(*args)
            self._output_errors.pop(index, None)
        except Exception as exc:
            logger.exception("Output error in %s", func)
            self._output_errors[index] = (str(exc)[:300], time.monotonic())

    @staticmethod
    def _safe_call(func, *args) -> None:
        try:
            func(*args)
        except Exception:
            logger.exception("Output error in %s", func)

    def get_health(self) -> dict:
        """Return runtime health data for the /health endpoint."""
        now = time.monotonic()
        np = self._current
        return {
            "uptime_seconds": round(now - self._start_time, 1),
            "poll_interval_seconds": self.poll_interval_seconds,
            "rotation_interval_seconds": self.rotation_interval_seconds,
            "now_playing": {
                "source": np.source,
                "media_type": np.media_type,
                "title": np.title,
                "subtitle": np.subtitle,
                "images": [a.label or a.url for a in np.images],
            } if np else None,
            "active_source": self._active_source_name,
            "source_last_polled_ago": {
                name: round(now - ts, 1) for name, ts in self._source_polled.items()
            },
            "source_backoff_seconds": {
                name: round(max(state.next_attempt - now, 0), 1)
                for name, state in self._source_backoff.items()
            },
            "output_errors": {
                i: {"message": msg, "ago_seconds": round(now - ts, 1)}
                for i, (msg, ts) in self._output_errors.items()
            },
            "idle_wallpapers_loaded": len(self._idle_images),
        }
