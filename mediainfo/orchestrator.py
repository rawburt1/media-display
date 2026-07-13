"""Orchestrator: owns the poll loop's lifecycle and wires together the
collaborators that do the actual work - source polling
(orchestrator_polling), artwork/enrichment (orchestrator_artwork),
per-tick routing (orchestrator_routing), idle-wallpaper batching
(orchestrator_idle), and output health tracking (orchestrator_health).

_tick, _poll_sources, and the _groups property are thin wrappers around
those collaborators, kept because _run() and Orchestrator's own methods
(_refresh_artwork, _force_rotation, get_health) call them directly - not
merely for tests. Tests exercise the collaborators themselves
(_SourcePoller.poll, _RoutingEngine.tick, orchestrator_state.classify)
rather than reaching into Orchestrator's private single-group state.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import List, Optional

from mediainfo.alerting import AlertManager
from mediainfo.stores.artwork_overrides import ArtworkOverrideStore
from mediainfo.cache import ImageCache
from mediainfo.config import AlertConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.enrichers.text_base import TextEnricher
from mediainfo.stores.history import PlaybackHistory
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import NowPlaying
from mediainfo.orchestrator_artwork import _DEFAULT_ENRICHMENT_DEADLINE_SECONDS, _ArtworkPipeline
from mediainfo.orchestrator_health import _HealthTracker
from mediainfo.orchestrator_idle import _IdleBatchManager
from mediainfo.orchestrator_polling import _SourcePoller
from mediainfo.orchestrator_routing import _RoutingEngine
from mediainfo.orchestrator_state import _RouteGroup, _strip_parenthetical
from mediainfo.outputs.base import Output
from mediainfo.stores.poster_store import PosterStore
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

_CACHE_PURGE_INTERVAL_SECONDS = 24 * 60 * 60

# How often to check whether any output has been failing long enough to
# fire an alert - independent of (and much coarser-grained than) the poll
# loop itself, since this is just a periodic health check, not something
# that needs to react within a single poll interval.
_ALERT_CHECK_INTERVAL_SECONDS = 60

# How often the watchdog supervisor thread (see _supervise) checks whether
# the poll loop is still ticking. Deliberately its own thread rather than a
# check inside _tick() itself - a hung _tick() call never returns control
# to _run() to run any check of its own, so only a genuinely separate
# thread can notice a stuck/dead poll loop from the outside.
_WATCHDOG_CHECK_INTERVAL_SECONDS = 30

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
        text_enrichers: Optional[List[TextEnricher]] = None,
        enrichment_deadline_seconds: float = _DEFAULT_ENRICHMENT_DEADLINE_SECONDS,
    ):
        self.sources = sources
        self.enrichers = enrichers
        self.text_enrichers = text_enrichers or []
        self.outputs = outputs
        self.cache = cache
        self.poll_interval_seconds = poll_interval_seconds
        self.rotation_interval_seconds = rotation_interval_seconds
        self.idle_source = idle_source
        self.backoff_initial_seconds = backoff_initial_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self.nothing_playing_grace_seconds = nothing_playing_grace_seconds
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
        # Set cross-thread (e.g. by an MQTT "refresh artwork" command) to
        # ask the next tick to re-enrich and re-push whatever is currently
        # playing - see request_artwork_refresh(). Checked and cleared on
        # the orchestrator's own thread in _tick(), same reasoning as
        # hitster-safe above: route-group state (group.current,
        # rotation_state, ...) has no locking of its own because only the
        # orchestrator thread ever touches it, so acting on the request
        # must happen there too rather than immediately on the caller's
        # thread.
        self._refresh_artwork_requested = threading.Event()
        # Set cross-thread (e.g. by an MQTT "next image" command) to ask
        # the next tick to immediately advance every output's rotation,
        # without waiting for rotation_interval_seconds to elapse - see
        # request_rotation_now(). Same cross-thread-flag-checked-on-the-
        # orchestrator's-own-thread reasoning as refresh-artwork above.
        self._rotate_now_requested = threading.Event()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._watchdog_thread = threading.Thread(target=self._supervise, daemon=True)
        # How stale seconds_since_last_tick must get before the watchdog
        # logs a CRITICAL line - scaled off poll_interval_seconds (so a
        # fast-polling setup gets a tighter alarm) with a floor, so a very
        # short poll interval doesn't make the watchdog trigger-happy over
        # a single slow tick.
        self._watchdog_stale_seconds = max(poll_interval_seconds * 6, 60)
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
            text_enrichers=text_enrichers,
            enrichment_deadline_seconds=enrichment_deadline_seconds,
        )
        self._idle = _IdleBatchManager(
            outputs=self.outputs,
            cache=self.cache,
            rotation_interval_seconds=self.rotation_interval_seconds,
            call_output=self._call_output,
            build_rotation_states=self._artwork.build_rotation_states,
            idle_source=idle_source,
        )
        self._router = _RoutingEngine(
            outputs=self.outputs,
            cache=self.cache,
            artwork=self._artwork,
            idle=self._idle,
            call_output=self._call_output,
            rotation_interval_seconds=self.rotation_interval_seconds,
            nothing_playing_grace_seconds=self.nothing_playing_grace_seconds,
        )
        self._alerts = AlertManager(alert_config or AlertConfig())
        self._last_alert_check: Optional[float] = None
        # Note: reassignable after construction (see tests) - _tick reads
        # it fresh each call rather than handing it to _artwork once.
        self._history = history

    @property
    def _groups(self) -> List[_RouteGroup]:
        return self._router.groups

    def get_hitster_safe(self) -> bool:
        with self._hitster_safe_lock:
            return self._hitster_safe

    def set_hitster_safe(self, enabled: bool) -> None:
        with self._hitster_safe_lock:
            self._hitster_safe = enabled
        logger.info("Hitster-safe mode %s", "enabled" if enabled else "disabled")

    def request_artwork_refresh(self) -> None:
        """Ask the orchestrator to re-enrich and re-push artwork for
        whatever is currently playing on its very next tick, without
        waiting for a track change - e.g. for a "refresh artwork" button
        (see the mqtt output's Home Assistant discovery). Safe to call
        from any thread; the actual work happens on the orchestrator's
        own thread (see _tick()).
        """
        self._refresh_artwork_requested.set()

    def request_rotation_now(self) -> None:
        """Ask the orchestrator to immediately advance every output's
        image rotation on its very next tick, without waiting for
        rotation_interval_seconds to elapse - e.g. for a "next image"
        button (see the mqtt output's Home Assistant discovery). Safe to
        call from any thread; the actual work happens on the
        orchestrator's own thread (see _tick()). A no-op for any group
        with nothing currently playing - there's nothing to advance to.
        """
        self._rotate_now_requested.set()

    def start(self) -> None:
        self._thread.start()
        self._watchdog_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def join(self) -> None:
        self._thread.join()
        self._watchdog_thread.join()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("Unexpected error in orchestrator loop")
            # Recorded after _tick() returns (successfully or via the
            # except above) rather than before it runs, so staleness
            # genuinely means "one full iteration hasn't completed in this
            # long" - if _tick() itself hangs (e.g. a device call with no
            # timeout), this line is simply never reached again, which is
            # exactly the condition _supervise() needs to detect.
            self._health.record_tick(time.monotonic())
            self._stop_event.wait(self.poll_interval_seconds)

    def _supervise(self) -> None:
        """Runs on its own daemon thread for the orchestrator's whole
        lifetime, independent of _run() - see _WATCHDOG_CHECK_INTERVAL_SECONDS
        and _watchdog_stale_seconds. This is the "thread supervisor" from
        M7 in docs/architecture-usability-review-2026-07.md: nothing inside
        _run()/_tick() can notice its own thread being stuck or dead, so
        only a genuinely separate thread can.
        """
        check_interval = min(_WATCHDOG_CHECK_INTERVAL_SECONDS, self._watchdog_stale_seconds)
        while not self._stop_event.wait(check_interval):
            self._check_watchdog()

    def _check_watchdog(self) -> None:
        now = time.monotonic()
        last_tick_at = self._health.last_tick_at
        if last_tick_at is None:
            return  # hasn't completed its first tick yet - not stale, just starting
        stale_for = now - last_tick_at
        is_stale = stale_for >= self._watchdog_stale_seconds
        if is_stale:
            logger.critical(
                "Orchestrator poll loop hasn't completed a tick in %.0fs (expected every "
                "%.0fs) - it may be stuck or dead",
                stale_for,
                self.poll_interval_seconds,
            )
        self._alerts.check_watchdog(last_tick_at if is_stale else None, now)

    def _tick(self) -> None:
        self._maybe_purge_cache()
        self._maybe_check_alerts()

        if self._refresh_artwork_requested.is_set():
            self._refresh_artwork_requested.clear()
            self._refresh_artwork()

        if self._rotate_now_requested.is_set():
            self._rotate_now_requested.clear()
            self._force_rotation()

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

        self._router.tick(results, self._history)

    def _refresh_artwork(self) -> None:
        """Re-enrich and re-push each group's current item, if any - see
        request_artwork_refresh(). Deliberately doesn't call
        output.on_new_item() (the item itself hasn't changed, just its
        artwork), matching how _maybe_rotate's periodic re-push works.
        """
        for group in self._groups:
            if group.current is None:
                continue
            self._artwork.enrich_item(group.current)
            if not group.current.images:
                continue
            group.rotation_state = self._artwork.build_rotation_states(
                len(group.current.images), group.output_indices
            )
            for index in group.output_indices:
                if index not in group.filtered_outputs:
                    self._artwork.show_image_for_output(group, index, self.outputs[index])

    def _force_rotation(self) -> None:
        """Reset every group's rotation clock so _router.tick()'s normal
        periodic-rotation check (_maybe_rotate: now - last_rotation vs.
        rotation_interval_seconds) treats every output as due right now,
        later in this same tick - see request_rotation_now(). Groups with
        nothing currently playing simply have no effect (_maybe_rotate
        returns immediately for those).
        """
        for group in self._groups:
            for state in group.rotation_state.values():
                # -inf, not 0.0: last_rotation is compared against
                # time.monotonic(), which counts from an arbitrary epoch
                # (often boot time) rather than the Unix epoch - on a
                # freshly booted machine it can be smaller than
                # rotation_interval_seconds, making `now - 0.0` read as
                # "not due yet" and silently swallowing the forced
                # rotation.
                state.last_rotation = float("-inf")

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
        self._alerts.check(
            labels,
            self._health.output_error_since,
            now,
            self._health.source_error_since,
        )

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
        data["now_playing"] = (
            {
                "source": np.source,
                "media_type": np.media_type,
                "title": np.title,
                "subtitle": np.subtitle,
                "images": [a.label or a.url for a in np.images],
            }
            if np
            else None
        )
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
