"""Idle-wallpaper batch management: fetching a fresh batch from the
configured idle source, rotating through it across outputs, and notifying
outputs (image-capable or not) when there's nothing to show.

Split out of orchestrator.py - holds the idle-specific state (the current
batch, its per-output rotation, when it was last fetched) that previously
lived as four separate Orchestrator attributes. `random.shuffle`/
`random.uniform` for building rotation state deliberately stay in
orchestrator.py (via the `build_rotation_states` callback passed in here)
so that module's existing test patches keep working unchanged.

The last successfully-fetched batch is also persisted to a small JSON file
under the cache's idle directory, and reloaded on construction - so if the
idle source (e.g. Unsplash) is unreachable right after a restart, outputs
still have the previous batch to show instead of going blank, as long as
its underlying cached image files haven't since been purged (see
cache.idle_max_age_hours).
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from mediainfo.cache import ImageCache
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output

if TYPE_CHECKING:
    from mediainfo.orchestrator_state import _RotationState

logger = logging.getLogger(__name__)

_PERSIST_FILENAME = "last_idle_batch.json"
_TEMP_DIR = Path(tempfile.gettempdir()).resolve()


def _unlink_temp(path: Optional[Path]) -> None:
    """Delete path only if it lives in the system temp directory."""
    if path is None:
        return
    try:
        if path.resolve().is_relative_to(_TEMP_DIR):
            path.unlink(missing_ok=True)
    except Exception:
        pass


class _IdleBatchManager:
    def __init__(
        self,
        outputs: List[Output],
        cache: ImageCache,
        rotation_interval_seconds: float,
        call_output: Callable[..., None],
        build_rotation_states: Callable[[int, List[int]], Dict[int, "_RotationState"]],
        idle_source: Optional[IdleWallpaperSource] = None,
    ):
        self.outputs = outputs
        self.cache = cache
        self.rotation_interval_seconds = rotation_interval_seconds
        self._call_output = call_output
        self._build_rotation_states = build_rotation_states
        self.idle_source = idle_source
        # The transform_pipeline of whichever source produced the current
        # batch (self.images) - see refetch() and _show_image_for_output().
        # [] until the first successful refetch; a batch loaded from disk
        # at startup has no known attribution either, so this stays []
        # until the next live fetch succeeds (self-healing, not persisted).
        self._current_transform_pipeline: List = []
        self._persist_path = self.cache.idle_dir / _PERSIST_FILENAME
        self.images: List[Artwork] = self._load_persisted_batch()
        self.rotation_state: Dict[int, "_RotationState"] = {}
        # Which outputs idle handling may currently touch - set by show()
        # from the orchestrator's route groups every tick. Defaults to
        # every output so direct refetch()/rotate() calls (tests) behave
        # like the pre-routing single-group orchestrator.
        self.notify_indices: set = set(range(len(outputs)))
        self.wallpaper_indices: set = set(range(len(outputs)))
        # Outputs that have received at least one push from the current
        # batch. An output (re)joining the wallpaper set mid-batch - its
        # route group just went idle - gets its first wallpaper immediately
        # in rotate() instead of waiting out its rotation interval.
        self._pushed: set = set()
        self.now_playing: Optional[NowPlaying] = (
            NowPlaying(source="idle", media_type="wallpaper", title="", subtitle="", images=self.images)
            if self.images
            else None
        )
        # None (not "now") deliberately - a seeded-from-disk batch is not a
        # fresh fetch, so the very first show() still tries the real idle
        # source rather than waiting out a full rotation_interval_seconds.
        # (Must be a sentinel rather than 0.0: needs_refetch() compares
        # against time.monotonic(), whose absolute value is unspecified -
        # on a freshly-booted machine it can be smaller than
        # rotation_interval_seconds, which made 0.0 indistinguishable from
        # "just fetched".)
        self.last_batch_fetch: Optional[float] = None

    def clear_if_stale(self) -> None:
        """Drop the batch so playback ending later triggers a fresh fetch.

        The orchestrator calls this only once *every* route group is
        showing real artwork (see _maybe_clear_stale_idle_state) - clearing
        while any group is still idle would blank its outputs.
        """
        if self.images:
            self.images = []
            self.rotation_state = {}
            self._pushed = set()
            self.last_batch_fetch = None

    def show(self, now: float, notify_indices: set, wallpaper_indices: set) -> None:
        """Show idle wallpapers on the given outputs.

        notify_indices: outputs of fully idle groups - they get on_idle()
        notifications (and wallpapers, for image-capable ones).
        wallpaper_indices: superset that additionally includes outputs of
        groups whose current item has no artwork - those get wallpapers on
        image outputs without text outputs being told to go idle.
        """
        self.notify_indices = set(notify_indices)
        self.wallpaper_indices = set(wallpaper_indices)
        # Outputs that left the wallpaper set (their group bound an item)
        # get a fresh immediate push in rotate() when they return.
        self._pushed &= self.wallpaper_indices

        # Non-image outputs (e.g. Ulanzi text, video player) always manage
        # their own idle display; notify them regardless of idle_source.
        self._notify_outputs(handles_images=False)

        if self.idle_source is None:
            self._notify_outputs(handles_images=True)
            return

        if self.needs_refetch(now):
            fetched = self.refetch(now)
            if not fetched and not self.images:
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
            or self.last_batch_fetch is None
            or now - self.last_batch_fetch >= self.idle_source.rotation_interval_seconds
        )

    def _notify_outputs(self, handles_images: bool) -> None:
        for i in sorted(self.notify_indices):
            output = self.outputs[i]
            if bool(output.handles_images) == handles_images:
                self._call_output(i, output.on_idle)

    def refetch(self, now: float) -> bool:
        """Fetch a fresh idle wallpaper batch and show it on every
        image-capable output.

        If the idle source had nothing to offer (e.g. unreachable), falls
        back to re-showing whatever batch is already in self.images
        (carried over from earlier this process, or loaded from disk at
        startup) instead of leaving outputs blank - but only pushes it if
        it hasn't already been shown in this process (self.rotation_state
        empty); an already-showing batch is left alone here and picked up
        by the normal rotate()/timing path instead. Returns False only
        when there is truly nothing - fresh or previous - to show.
        """
        assert self.idle_source is not None
        images = self.idle_source.get_wallpapers()
        if images:
            logger.info("Fetched %d idle wallpaper(s)", len(images))
            self.images = images
            self.now_playing = NowPlaying(
                source="idle", media_type="wallpaper", title="", subtitle="", images=images
            )
            self.last_batch_fetch = now
            # Whichever source actually produced this batch - the
            # CompositeIdleWallpaperSource case (last_used) and the
            # single-source case (idle_source itself) both handled by the
            # same getattr, since only one source's pictures ever make up
            # a given batch (see idle/composite.py). The second getattr
            # tolerates duck-typed idle sources (e.g. test doubles) that
            # predate transform_pipeline and don't define it.
            winner = getattr(self.idle_source, "last_used", self.idle_source)
            self._current_transform_pipeline = list(getattr(winner, "transform_pipeline", []) or [])
            self._push_current_batch()
            self._save_persisted_batch(images)
            return True

        if self.images and not self.rotation_state:
            logger.warning(
                "Idle source returned no wallpapers (unavailable?) - "
                "showing the previous batch of %d instead of going blank",
                len(self.images),
            )
            self._push_current_batch()
            return True

        return False

    def _push_current_batch(self) -> None:
        # Rotation states are built for every output (so one joining the
        # wallpaper set mid-batch already has a position), but only the
        # current wallpaper set is actually pushed to - outputs bound to a
        # playing item must not be told about the idle batch.
        self.rotation_state = self._build_rotation_states(
            len(self.images), list(range(len(self.outputs)))
        )
        self._pushed = set()
        for index in sorted(self.wallpaper_indices):
            self._call_output(index, self.outputs[index].on_new_item, self.now_playing, self.cache)
        for index in sorted(self.wallpaper_indices):
            self._show_image_for_output(index, self.outputs[index])
            self._pushed.add(index)

    def _load_persisted_batch(self) -> List[Artwork]:
        try:
            if not self._persist_path.exists():
                return []
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
            return [Artwork(url=item["url"], label=item.get("label", "")) for item in raw]
        except Exception:
            # Low severity and non-fatal either way - just means starting
            # with no previous batch to fall back on, same as a fresh
            # install. Logged at debug rather than as an error/exception
            # to avoid alarming output for what's just a missing/garbled
            # optional file.
            logger.debug("No usable persisted idle wallpaper batch", exc_info=True)
            return []

    def _save_persisted_batch(self, images: List[Artwork]) -> None:
        try:
            raw = [{"url": a.url, "label": a.label} for a in images]
            self._persist_path.write_text(json.dumps(raw), encoding="utf-8")
        except Exception:
            logger.exception("Failed to persist idle wallpaper batch")

    def rotate(self, now: float) -> None:
        """Advance (or, for a single-wallpaper batch, simply re-push) each
        output's current pick once its rotation_interval_seconds elapses -
        see Orchestrator._maybe_rotate for why a single-image batch still
        needs this rather than being skipped entirely (a failed push is
        otherwise never retried for as long as that batch is current)."""
        if not self.images:
            return

        multi_image = len(self.images) > 1
        for index in sorted(self.wallpaper_indices):
            output = self.outputs[index]
            state = self.rotation_state.get(index)
            if state is None:
                continue

            if index not in self._pushed:
                # This output's group just went idle mid-batch: show it a
                # wallpaper now (with the batch's on_new_item first, the
                # same order _push_current_batch uses) rather than leaving
                # its previous item up for the rest of a rotation interval.
                self._pushed.add(index)
                state.last_rotation = now
                self._call_output(index, output.on_new_item, self.now_playing, self.cache)
                self._show_image_for_output(index, output)
                continue

            if now - state.last_rotation < self.rotation_interval_seconds:
                continue

            if multi_image:
                state.position = (state.position + 1) % len(state.order)
            state.last_rotation = now
            self._show_image_for_output(index, output)

    def _show_image_for_output(self, index: int, output: Output) -> None:
        """Resolve and push the output's current rotation pick - falling
        through the rest of the batch (in rotation order) if that pick
        fails to fetch (e.g. rejected by the cache's minimum-size filter),
        rather than leaving the output showing nothing until its next
        scheduled rotation.
        """
        if not output.handles_images:
            return
        state = self.rotation_state[index]

        for attempt in range(len(self.images)):
            artwork = self.images[state.order[(state.position + attempt) % len(state.order)]]
            original_path = None
            try:
                original_path = self.cache.download_temp(artwork)
                if original_path is None:
                    continue
                # Source-level styling (e.g. arts' own crop/filter) runs
                # first, then whatever this specific output's own pipeline
                # applies - see _current_transform_pipeline in refetch().
                pipeline = self._current_transform_pipeline + output.transform_pipeline
                image_path = self.cache.get_transformed_path(original_path, pipeline)
            except Exception:
                logger.exception("Failed to fetch idle wallpaper %s", artwork.url)
                _unlink_temp(original_path)
                continue

            logger.info("Idle wallpaper: %s", artwork.label)
            self._call_output(index, output.update, self.now_playing, artwork, image_path)
            _unlink_temp(original_path)
            if image_path is not original_path:
                _unlink_temp(image_path)
            return
