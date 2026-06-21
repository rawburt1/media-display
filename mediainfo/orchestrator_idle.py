"""Idle-wallpaper batch management: fetching a fresh batch from the
configured idle source, rotating through it across outputs, and notifying
outputs (image-capable or not) when there's nothing to show.

Split out of orchestrator.py - holds the idle-specific state (the current
batch, its per-output rotation, when it was last fetched) that previously
lived as four separate Orchestrator attributes. `random.shuffle`/
`random.uniform` for building rotation state deliberately stay in
orchestrator.py (via the `build_rotation_states` callback passed in here)
so that module's existing test patches keep working unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from mediainfo.cache import ImageCache
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output

if TYPE_CHECKING:
    from mediainfo.orchestrator import _RotationState

logger = logging.getLogger(__name__)


class _IdleBatchManager:
    def __init__(
        self,
        outputs: List[Output],
        cache: ImageCache,
        rotation_interval_seconds: float,
        call_output: Callable[..., None],
        build_rotation_states: Callable[[int, int], Dict[int, "_RotationState"]],
        idle_source: Optional[IdleWallpaperSource] = None,
    ):
        self.outputs = outputs
        self.cache = cache
        self.rotation_interval_seconds = rotation_interval_seconds
        self._call_output = call_output
        self._build_rotation_states = build_rotation_states
        self.idle_source = idle_source
        self.images: List[Artwork] = []
        self.rotation_state: Dict[int, "_RotationState"] = {}
        self.now_playing: Optional[NowPlaying] = None
        self.last_batch_fetch = 0.0

    def clear_if_stale(self, now_playing: NowPlaying) -> None:
        """Clear the idle batch only once real artwork is available again."""
        if now_playing.images and self.images:
            self.images = []
            self.rotation_state = {}
            self.last_batch_fetch = 0.0

    def show(self, now: float, notify_idle: bool = True) -> None:
        """Show idle wallpapers on image-capable outputs.

        notify_idle controls whether on_idle() is called (set to False when
        something is playing but has no artwork, so outputs keep their
        current display instead of clearing).
        """
        # Non-image outputs (e.g. Ulanzi text, video player) always manage
        # their own idle display; notify them regardless of idle_source.
        if notify_idle:
            self._notify_outputs(handles_images=False)

        if self.idle_source is None:
            if notify_idle:
                self._notify_outputs(handles_images=True)
            return

        if self.needs_refetch(now):
            fetched = self.refetch(now)
            if not fetched and not self.images and notify_idle:
                self._notify_outputs(handles_images=True)
            return

        self.rotate(now)

    def needs_refetch(self, now: float) -> bool:
        """Pure: is it time to ask the idle source for a fresh batch -
        because we don't have one at all, or because the configured
        rotation_interval_seconds has elapsed since the last fetch?
        """
        assert self.idle_source is not None
        return (
            not self.images
            or now - self.last_batch_fetch >= self.idle_source.rotation_interval_seconds
        )

    def _notify_outputs(self, handles_images: bool) -> None:
        for i, output in enumerate(self.outputs):
            if bool(output.handles_images) == handles_images:
                self._call_output(i, output.on_idle)

    def refetch(self, now: float) -> bool:
        """Fetch a fresh idle wallpaper batch and show it on every
        image-capable output. Returns False, leaving any existing batch
        untouched, if the idle source had nothing to offer.
        """
        assert self.idle_source is not None
        images = self.idle_source.get_wallpapers()
        if not images:
            return False

        logger.info("Fetched %d idle wallpaper(s)", len(images))
        self.images = images
        self.now_playing = NowPlaying(
            source="idle", media_type="wallpaper", title="", subtitle="", images=images
        )
        self.last_batch_fetch = now
        self.rotation_state = self._build_rotation_states(len(images), len(self.outputs))
        for index, output in enumerate(self.outputs):
            self._call_output(index, output.on_new_item, self.now_playing, self.cache)
        for index, output in enumerate(self.outputs):
            self._show_image_for_output(index, output)
        return True

    def rotate(self, now: float) -> None:
        if len(self.images) <= 1:
            return

        for index, output in enumerate(self.outputs):
            state = self.rotation_state.get(index)
            if state is None or now - state.last_rotation < self.rotation_interval_seconds:
                continue

            state.position = (state.position + 1) % len(state.order)
            state.last_rotation = now
            self._show_image_for_output(index, output)

    def _show_image_for_output(self, index: int, output: Output) -> None:
        if not output.handles_images:
            return
        state = self.rotation_state[index]
        artwork = self.images[state.order[state.position]]
        try:
            image_path = self.cache.get_path(artwork, tier="idle")
            if image_path is None:
                return
            image_path = self.cache.get_transformed_path(image_path, output.transform_pipeline)
        except Exception:
            logger.exception("Failed to fetch idle wallpaper %s", artwork.url)
            return

        logger.info("Idle wallpaper: %s", artwork.label)
        self._call_output(index, output.update, self.now_playing, artwork, image_path)
