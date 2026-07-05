"""Polling loop: picks the highest-priority active source, enriches it with
extra artwork, and rotates through the available images on enabled outputs.
"""

from __future__ import annotations

import logging
import random  # noqa: F401 - unused directly; kept so tests' patch("mediainfo.orchestrator.random...") still resolves
import threading
import time
from typing import Dict, List, Optional

from mediainfo.alerting import AlertManager
from mediainfo.artwork_overrides import ArtworkOverrideStore
from mediainfo.cache import ImageCache
from mediainfo.config import AlertConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.history import PlaybackHistory
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import NowPlaying
from mediainfo.orchestrator_artwork import _ArtworkPipeline
from mediainfo.orchestrator_health import _HealthTracker
from mediainfo.orchestrator_idle import _IdleBatchManager
from mediainfo.orchestrator_polling import _group_accepts, _SourcePoller
from mediainfo.orchestrator_state import (
    _RotationState,
    _RouteGroup,
    _strip_parenthetical,
    _Transition,
    build_groups,
)
from mediainfo.orchestrator_state import classify as _classify_group
from mediainfo.output_filter import passes_filter
from mediainfo.outputs.base import Output
from mediainfo.poster_store import PosterStore
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

_CACHE_PURGE_INTERVAL_SECONDS = 24 * 60 * 60

# How often to check whether any output has been failing long enough to
# fire an alert - independent of (and much coarser-grained than) the poll
# loop itself, since this is just a periodic health check, not something
# that needs to react within a single poll interval.
_ALERT_CHECK_INTERVAL_SECONDS = 60

# Default for the nothing_playing_grace_seconds constructor param below
# (overridable via Config.nothing_playing_grace_seconds) - how long to
# tolerate a source reporting "nothing playing" before actually switching
# outputs to idle, while something was already playing. Some sources
# briefly report no active session for a single poll or two during normal
# playback (e.g. Kodi's active-player list can momentarily come back
# empty around a chapter/scene transition) - without this grace period,
# that one missed poll flashes every output to idle and back, including a
# full re-enrichment cycle, even though playback never actually stopped. A
# source that's cold (nothing has played yet this run) is unaffected -
# this only applies once something is already showing.
_DEFAULT_NOTHING_PLAYING_GRACE_SECONDS = 2


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
        backoff_initial_seconds: float = 30,
        backoff_max_seconds: float = 300,
        nothing_playing_grace_seconds: float = _DEFAULT_NOTHING_PLAYING_GRACE_SECONDS,
        alert_config: Optional[AlertConfig] = None,
        overrides: Optional[ArtworkOverrideStore] = None,
        poster_store: Optional[PosterStore] = None,
        history: Optional[PlaybackHistory] = None,
    ):
        self.sources = sources
        self.enrichers = enrichers
        self.outputs = outputs
        self.cache = cache
        self.poll_interval_seconds = poll_interval_seconds
        self.rotation_interval_seconds = rotation_interval_seconds
        self.idle_source = idle_source
        self.backoff_initial_seconds = backoff_initial_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self.nothing_playing_grace_seconds = nothing_playing_grace_seconds
        # Route groups (see _RouteGroup): every output lives in exactly one
        # group; a group's outputs share the item they show.
        self._groups: List[_RouteGroup] = build_groups(outputs)
        self._last_cache_purge: Optional[float] = None
        # "Hitster-safe" mode: while enabled, music now-playing (songs,
        # artists, albums) is treated as if nothing were playing on every
        # output - so the title/artist never leaks on screen during a game
        # of Hitster (or similar music-guessing games). Toggled cross-thread
        # via the web output's UI, so it's guarded by its own lock rather
        # than relying on the orchestrator thread being the only
        # reader/writer.
        self._hitster_safe = False
        self._hitster_safe_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._health = _HealthTracker()
        self._poller = _SourcePoller(
            health=self._health,
            get_hitster_safe=self.get_hitster_safe,
            backoff_initial_seconds=backoff_initial_seconds,
            backoff_max_seconds=backoff_max_seconds,
        )
        self._artwork = _ArtworkPipeline(
            enrichers=self.enrichers,
            cache=self.cache,
            rotation_interval_seconds=self.rotation_interval_seconds,
            call_output=self._call_output,
            safe_call=self._safe_call,
            poster_store=poster_store,
            overrides=overrides,
        )
        self._idle = _IdleBatchManager(
            outputs=self.outputs,
            cache=self.cache,
            rotation_interval_seconds=self.rotation_interval_seconds,
            call_output=self._call_output,
            build_rotation_states=self._artwork.build_rotation_states,
            idle_source=idle_source,
        )
        self._alerts = AlertManager(alert_config or AlertConfig())
        self._last_alert_check: Optional[float] = None
        # Note: reassignable after construction (see tests) - _tick reads
        # it fresh each call rather than handing it to _artwork once.
        self._history = history

    # -- single-group state aliases -----------------------------------------
    # The orchestrator's original single-item attributes, aliased to the
    # first route group's state - kept for tests and get_health(), which
    # predate route groups. Internal code passes an explicit group instead.

    @property
    def _current(self) -> Optional[NowPlaying]:
        return self._groups[0].current

    @_current.setter
    def _current(self, value: Optional[NowPlaying]) -> None:
        self._groups[0].current = value

    @property
    def _rotation_state(self) -> Dict[int, _RotationState]:
        return self._groups[0].rotation_state

    @property
    def _filtered_outputs(self) -> set:
        return self._groups[0].filtered_outputs

    @property
    def _nothing_playing_since(self) -> Optional[float]:
        return self._groups[0].nothing_playing_since

    def get_hitster_safe(self) -> bool:
        with self._hitster_safe_lock:
            return self._hitster_safe

    def set_hitster_safe(self, enabled: bool) -> None:
        with self._hitster_safe_lock:
            self._hitster_safe = enabled
        logger.info("Hitster-safe mode %s", "enabled" if enabled else "disabled")

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
        self._maybe_check_alerts()

        # Time-based device housekeeping (power/brightness schedules) runs
        # for every output every tick, filtered or not - via _safe_call
        # rather than _call_output, so a no-op here never clears (or a
        # schedule hiccup never sets) an output's update() health state.
        # getattr: tolerate duck-typed outputs (tests) that don't inherit
        # Output, same as the `config`/`last_poll_failed` accesses do.
        for output in self.outputs:
            tick = getattr(output, "on_schedule_tick", None)
            if tick is not None:
                self._safe_call(tick)

        results = self._poll_sources()
        # Stripped here, once per poll result, rather than per group - so
        # groups sharing an item never double-process it.
        for item in results:
            if item.media_type == "music":
                item.title = _strip_parenthetical(item.title)

        # Route: each group gets the highest-priority result it accepts.
        # `prepared` deduplicates enrichment when several groups pick the
        # same item this tick (see _prepare_item).
        prepared: Dict[tuple, NowPlaying] = {}
        for group in self._groups:
            routed = next((r for r in results if _group_accepts(group, r)), None)
            prepared_item = self._artwork.prepare_item(
                self._groups, group, routed, prepared, self._history
            )
            self._tick_group(group, prepared_item)

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

        transition = self._classify(group, now_playing)
        if transition is _Transition.SAME_ITEM_ROTATE:
            self._refresh_position(group, now_playing)
            self._maybe_rotate(group)
        elif transition is _Transition.SAME_ITEM_NO_ARTWORK:
            self._refresh_position(group, now_playing)
            # Same no-artwork item: the group's image outputs stay in the
            # idle-wallpaper set computed at the end of _tick, without
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

    def _resolve_now_playing(self) -> Optional[NowPlaying]:
        """The highest-priority routed result, or None - the single-item
        view of _poll_sources(), kept for tests that predate routing."""
        results = self._poll_sources()
        return results[0] if results else None

    def _maybe_clear_stale_idle_state(self) -> None:
        """Drop the idle batch only once *every* group is showing real
        artwork again - clearing while any group is still idle (or showing
        wallpapers for an artwork-less item) would blank its outputs.
        """
        if all(g.current is not None and g.current.images for g in self._groups):
            self._idle.clear_if_stale()

    def _classify(self, group: _RouteGroup, now_playing: NowPlaying) -> _Transition:
        return _classify_group(group, now_playing)

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
        # Idle wallpapers themselves are pushed at the end of _tick (see
        # _show_idle), once every group has settled.

    def _handle_new_item(self, group: _RouteGroup, now_playing: NowPlaying) -> None:
        # Enrichment already happened in _prepare_item (shared across
        # groups picking the same item this tick).
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
            # end of this same _tick (see _idle_targets).
            return

        group.rotation_state = self._artwork.build_rotation_states(
            len(now_playing.images), group.output_indices
        )
        for index in group.output_indices:
            if index not in group.filtered_outputs:
                self._artwork.show_image_for_output(group, index, self.outputs[index])

    def _maybe_purge_cache(self) -> None:
        now = time.monotonic()
        if (
            self._last_cache_purge is not None
            and now - self._last_cache_purge < _CACHE_PURGE_INTERVAL_SECONDS
        ):
            return

        self._last_cache_purge = now
        self._safe_call(self.cache.purge_expired)

    def _maybe_check_alerts(self) -> None:
        now = time.monotonic()
        if (
            self._last_alert_check is not None
            and now - self._last_alert_check < _ALERT_CHECK_INTERVAL_SECONDS
        ):
            return

        self._last_alert_check = now
        labels = {i: type(output).__name__ for i, output in enumerate(self.outputs)}
        self._alerts.check(labels, self._health.output_error_since, now)

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

    def _idle_targets(self) -> tuple[set, set]:
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
        for group in self._groups:
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

    def _poll_sources(self) -> List[NowPlaying]:
        """The route groups' view of this tick's active sources - a thin
        wrapper kept for tests that predate the polling extraction; see
        _SourcePoller.poll() for the actual logic."""
        return self._poller.poll(self.sources, self._groups)

    def _call_output(self, index: int, func, *args) -> None:
        """Call an output method, recording any exception for health reporting."""
        try:
            func(*args)
            self._health.record_output_success(index)
        except Exception as exc:
            logger.exception("Output error in %s", func)
            self._health.record_output_error(index, str(exc), time.monotonic())

    @staticmethod
    def _safe_call(func, *args) -> None:
        try:
            func(*args)
        except Exception:
            logger.exception("Output error in %s", func)

    def get_health(self) -> dict:
        """Return runtime health data for the /health endpoint."""
        now = time.monotonic()
        # The highest-priority bound item, for the payload's original
        # single now_playing field - with no filters configured (one
        # group) this is exactly the pre-routing global winner.
        np = next((g.current for g in self._groups if g.current is not None), None)
        data = self._health.as_dict(now)
        data["poll_interval_seconds"] = self.poll_interval_seconds
        data["rotation_interval_seconds"] = self.rotation_interval_seconds
        data["now_playing"] = {
            "source": np.source,
            "media_type": np.media_type,
            "title": np.title,
            "subtitle": np.subtitle,
            "images": [a.label or a.url for a in np.images],
        } if np else None
        # What each output is currently bound to (per-output source
        # routing) - None while its group is idle or the output itself is
        # filtered (active_hours / idle_when_filtered).
        data["output_now_playing"] = {
            index: (
                None
                if group.current is None or index in group.filtered_outputs
                else {
                    "source": group.current.source,
                    "title": group.current.title,
                    "subtitle": group.current.subtitle,
                }
            )
            for group in self._groups
            for index in group.output_indices
        }
        data["idle_wallpapers_loaded"] = len(self._idle.images)
        data["hitster_safe"] = self.get_hitster_safe()
        return data
