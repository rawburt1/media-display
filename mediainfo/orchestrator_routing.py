"""Per-tick routing: advances each route group given what was polled this
tick, applies per-output content filters, drives image rotation, and hands
outputs that ended the tick unbound (or artwork-less) off to idle-wallpaper
handling.

Split out of orchestrator.py - owns the route groups themselves (built
once, for the life of the process, same as before) plus all group-state
transitions. `history` is taken as an argument to tick() rather than
captured at construction, for the same reason _ArtworkPipeline.prepare_item
takes it as an argument: Orchestrator._history can be reassigned after
construction (see tests) and the very next tick must see the change.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Dict, List, Optional

from mediainfo.cache import ImageCache
from mediainfo.history import PlaybackHistory
from mediainfo.models import NowPlaying
from mediainfo.orchestrator_artwork import _ArtworkPipeline
from mediainfo.orchestrator_idle import _IdleBatchManager
from mediainfo.orchestrator_polling import _group_accepts
from mediainfo.orchestrator_state import _RouteGroup, _Transition, build_groups, classify
from mediainfo.output_filter import passes_filter
from mediainfo.outputs.base import Output

logger = logging.getLogger(__name__)


class _RoutingEngine:
    def __init__(
        self,
        outputs: List[Output],
        cache: ImageCache,
        artwork: _ArtworkPipeline,
        idle: _IdleBatchManager,
        call_output: Callable[..., None],
        rotation_interval_seconds: float,
        nothing_playing_grace_seconds: float,
    ):
        self.outputs = outputs
        self.cache = cache
        self._artwork = artwork
        self._idle = idle
        self._call_output = call_output
        self.rotation_interval_seconds = rotation_interval_seconds
        self.nothing_playing_grace_seconds = nothing_playing_grace_seconds
        # Route groups (see _RouteGroup): every output lives in exactly one
        # group; a group's outputs share the item they show.
        self.groups: List[_RouteGroup] = build_groups(outputs)

    def tick(self, results: List[NowPlaying], history: Optional[PlaybackHistory]) -> None:
        # Route: each group gets the highest-priority result it accepts.
        # `prepared` deduplicates enrichment when several groups pick the
        # same item this tick (see _ArtworkPipeline.prepare_item).
        prepared: Dict[tuple, NowPlaying] = {}
        for group in self.groups:
            routed = next((r for r in results if _group_accepts(group, r)), None)
            item = self._artwork.prepare_item(self.groups, group, routed, prepared, history)
            self._tick_group(group, item)

        # Idle wallpapers go to whichever outputs ended this tick unbound
        # (or bound to an artwork-less item) - decided after every group
        # has settled, so one group going idle never touches another
        # group's outputs.
        self._show_idle()
        self._maybe_clear_stale_idle_state()

    def _tick_group(self, group: _RouteGroup, now_playing: Optional[NowPlaying]) -> None:
        """Advance one route group given the item routed to it this tick
        (None when nothing it accepts is playing)."""
        if now_playing is None:
            self._handle_nothing_playing(group)
            return

        group.nothing_playing_since = None

        transition = classify(group, now_playing)
        if transition is _Transition.SAME_ITEM_ROTATE:
            self._refresh_position(group, now_playing)
            self._maybe_rotate(group)
        elif transition is _Transition.SAME_ITEM_NO_ARTWORK:
            self._refresh_position(group, now_playing)
            # Same no-artwork item: the group's image outputs stay in the
            # idle-wallpaper set computed at the end of tick(), without
            # text-only outputs being notified to go idle.
        else:
            self._handle_new_item(group, now_playing)

    def _refresh_position(self, group: _RouteGroup, now_playing: NowPlaying) -> None:
        """Keep the group's current item's playback position/duration fresh
        from every poll, not just frozen at whatever it was when the item
        started - _maybe_rotate periodically re-pushes the current item to
        outputs (see its docstring).
        """
        assert group.current is not None  # only called for SAME_ITEM transitions
        group.current.position_seconds = now_playing.position_seconds
        group.current.duration_seconds = now_playing.duration_seconds

    def _maybe_clear_stale_idle_state(self) -> None:
        """Drop the idle batch only once *every* group is showing real
        artwork again - clearing while any group is still idle (or showing
        wallpapers for an artwork-less item) would blank its outputs.
        """
        if all(g.current is not None and g.current.images for g in self.groups):
            self._idle.clear_if_stale()

    def _handle_nothing_playing(self, group: _RouteGroup) -> None:
        if group.current is not None:
            now = time.monotonic()
            if group.nothing_playing_since is None:
                group.nothing_playing_since = now
            if now - group.nothing_playing_since < self.nothing_playing_grace_seconds:
                # Tolerate a brief gap without touching outputs at all - see
                # nothing_playing_grace_seconds above.
                return
            logger.info("Nothing playing; switching outputs to idle")
            group.current = None
            group.rotation_state = {}
            group.filtered_outputs = set()
            group.nothing_playing_since = None
        # Idle wallpapers themselves are pushed at the end of tick() (see
        # _show_idle), once every group has settled.

    def _handle_new_item(self, group: _RouteGroup, now_playing: NowPlaying) -> None:
        # Enrichment already happened in _ArtworkPipeline.prepare_item
        # (shared across groups picking the same item this tick).
        logger.info(
            "Now playing changed: [%s] %s - %s (%d image(s))",
            now_playing.source,
            now_playing.title,
            now_playing.subtitle,
            len(now_playing.images),
        )

        group.current = now_playing
        group.filtered_outputs = self._compute_filtered(group, now_playing)

        for index in group.output_indices:
            output = self.outputs[index]
            if index in group.filtered_outputs:
                if getattr(getattr(output, "config", None), "idle_when_filtered", False):
                    self._call_output(index, output.on_idle)
            else:
                self._call_output(index, output.on_new_item, now_playing, self.cache)

        if not now_playing.images:
            logger.warning("No artwork available for %s", now_playing.title)
            group.rotation_state = {}
            # The group's image outputs join the idle-wallpaper set at the
            # end of this same tick (see _idle_targets).
            return

        group.rotation_state = self._artwork.build_rotation_states(
            len(now_playing.images), group.output_indices
        )
        for index in group.output_indices:
            if index not in group.filtered_outputs:
                self._artwork.show_image_for_output(group, index, self.outputs[index])

    def _compute_filtered(self, group: _RouteGroup, now_playing: NowPlaying) -> set:
        """Return the group output indices that should be blocked for
        *now_playing*."""
        filtered = set()
        for index in group.output_indices:
            output = self.outputs[index]
            config = getattr(output, "config", None)
            if not passes_filter(now_playing, config):
                logger.debug(
                    "Output %d (%s) filtered for [%s/%s]",
                    index, type(output).__name__, now_playing.source, now_playing.media_type,
                )
                filtered.add(index)
        return filtered

    def _recheck_filters(self, group: _RouteGroup) -> None:
        """Re-evaluate filters for the group's outputs against its current
        item.

        Called on every rotation tick so that active_hours transitions
        (e.g. an output becoming active at 08:00 while the same item keeps
        playing) are applied without waiting for the next track change.
        """
        if group.current is None:
            return
        for index in group.output_indices:
            output = self.outputs[index]
            config = getattr(output, "config", None)
            was_filtered = index in group.filtered_outputs
            is_filtered = not passes_filter(group.current, config)
            if is_filtered == was_filtered:
                continue
            if is_filtered:
                group.filtered_outputs.add(index)
                logger.debug(
                    "Output %d (%s) became filtered mid-play",
                    index, type(output).__name__,
                )
                if getattr(config, "idle_when_filtered", False):
                    self._call_output(index, output.on_idle)
            else:
                group.filtered_outputs.discard(index)
                logger.debug(
                    "Output %d (%s) became unfiltered mid-play",
                    index, type(output).__name__,
                )
                self._call_output(index, output.on_new_item, group.current, self.cache)
                if group.current.images:
                    self._artwork.show_image_for_output(group, index, output)

    def _maybe_rotate(self, group: _RouteGroup) -> None:
        """Advance (or, for a single-image item, simply re-push) each
        group output's current pick once its rotation_interval_seconds
        elapses.

        Single-image items still go through this on schedule rather than
        being skipped entirely - a push that failed once (e.g. a physical
        display like a Pixoo64 being transiently unreachable) would
        otherwise never be retried for as long as that one item keeps
        playing, leaving the output frozen on whatever it last received
        (which could be a *previous*, unrelated item's artwork) until the
        next genuinely different item starts.
        """
        if group.current is None:
            return

        self._recheck_filters(group)

        now = time.monotonic()
        multi_image = len(group.current.images) > 1
        for index in group.output_indices:
            if index in group.filtered_outputs:
                continue
            state = group.rotation_state.get(index)
            if state is None or now - state.last_rotation < self.rotation_interval_seconds:
                continue

            if multi_image:
                state.position = (state.position + 1) % len(state.order)
            state.last_rotation = now
            self._artwork.show_image_for_output(group, index, self.outputs[index])

    def _idle_targets(self) -> "tuple[set, set]":
        """Which outputs idle handling may touch this tick.

        Returns (notify_indices, wallpaper_indices): outputs of fully idle
        groups get both on_idle() notifications and wallpapers; outputs of
        groups whose current item has no artwork get wallpapers only, so
        e.g. a text output keeps showing the item's title. Outputs of a
        group inside its nothing-playing grace window (current still set)
        are in neither - they keep their display untouched, exactly the
        pre-routing grace behavior.
        """
        notify: set = set()
        wallpaper: set = set()
        for group in self.groups:
            if group.current is None:
                notify.update(group.output_indices)
                wallpaper.update(group.output_indices)
            elif not group.current.images:
                wallpaper.update(group.output_indices)
        return notify, wallpaper

    def _show_idle(self) -> None:
        notify, wallpaper = self._idle_targets()
        if notify or wallpaper:
            self._idle.show(time.monotonic(), notify, wallpaper)
