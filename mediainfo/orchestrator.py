"""Polling loop: picks the highest-priority active source, enriches it with
extra artwork, and rotates through the available images on enabled outputs.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import random
import re
import threading
import time
from typing import Dict, List, Optional

from mediainfo.alerting import AlertManager
from mediainfo.artwork_overrides import ArtworkOverrideStore
from mediainfo.cache import CacheTier, ImageCache
from mediainfo.config import AlertConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import NowPlaying
from mediainfo.orchestrator_health import _BackoffState, _HealthTracker
from mediainfo.orchestrator_idle import _IdleBatchManager
from mediainfo.outputs.base import Output
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

_CACHE_PURGE_INTERVAL_SECONDS = 24 * 60 * 60

# How often to check whether any output has been failing long enough to
# fire an alert - independent of (and much coarser-grained than) the poll
# loop itself, since this is just a periodic health check, not something
# that needs to react within a single poll interval.
_ALERT_CHECK_INTERVAL_SECONDS = 60

# How long to tolerate a source reporting "nothing playing" before actually
# switching outputs to idle, while something was already playing. Some
# sources briefly report no active session for a single poll or two during
# normal playback (e.g. Kodi's active-player list can momentarily come back
# empty around a chapter/scene transition) - without this grace period, that
# one missed poll flashes every output to idle and back, including a full
# re-enrichment cycle, even though playback never actually stopped. A source
# that's cold (nothing has played yet this run) is unaffected - this only
# applies once something is already showing.
_NOTHING_PLAYING_GRACE_SECONDS = 2

# Backoff for sources whose device/service couldn't be reached (see
# MediaSource.last_poll_failed) - doubles after each consecutive failure,
# capped at backoff_max_seconds, and resets the moment a poll succeeds
# (connects fine, whether or not anything's playing). Sources that are
# simply idle - no error, nothing playing - are polled every tick as usual;
# only unreachable ones get backed off, so detection isn't delayed for
# devices that are just sitting there idle but reachable. The starting
# delay and cap are configurable (Config.backoff_initial_seconds/
# backoff_max_seconds) so operators can tune how aggressively to retry a
# flaky device vs. how much log/network noise that produces.
_BACKOFF_MULTIPLIER = 2

# Matches one or more consecutive "(...)" groups trailing a song title,
# e.g. "(Live)", "(Remastered 2011) (Mono Mix)" - stripped from every
# source's title uniformly here, rather than per-source, so every output
# shows the same clean title regardless of which source produced it.
# Anchored to the end so a leading or mid-title "(...)" that's actually
# part of the song's real name (e.g. "(I Can't Get No) Satisfaction")
# is left alone.
_PARENTHETICAL_RE = re.compile(r"(?:\s*\([^)]*\))+\s*$")


def _strip_parenthetical(title: str) -> str:
    return re.sub(r"\s{2,}", " ", _PARENTHETICAL_RE.sub("", title)).strip()


@dataclasses.dataclass
class _RotationState:
    """An output's independent position in a randomized cycle through
    `NowPlaying.images`."""

    order: List[int]
    position: int
    last_rotation: float


class _Transition(enum.Enum):
    """What kind of tick this is, decided purely from the current poll
    result and the orchestrator's existing state - before any enrichment,
    cache access, or output call happens. Keeping this decision free of
    side effects means it can be reasoned about (and tested) on its own,
    independently of mocking outputs/cache/enrichers.
    """

    NOTHING_PLAYING = enum.auto()
    SAME_ITEM_ROTATE = enum.auto()
    SAME_ITEM_NO_ARTWORK = enum.auto()
    NEW_ITEM = enum.auto()


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
        alert_config: Optional[AlertConfig] = None,
        overrides: Optional[ArtworkOverrideStore] = None,
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
        self._current: Optional[NowPlaying] = None
        # Each output independently cycles through `self._current.images` in
        # its own randomized order, keyed by its index in `self.outputs`.
        self._rotation_state: Dict[int, _RotationState] = {}
        self._last_cache_purge: Optional[float] = None
        # When the time it was first seen since `self._current` was set;
        # None means either nothing is playing or the source just resumed.
        # See _NOTHING_PLAYING_GRACE_SECONDS above.
        self._nothing_playing_since: Optional[float] = None
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
        self._idle = _IdleBatchManager(
            outputs=self.outputs,
            cache=self.cache,
            rotation_interval_seconds=self.rotation_interval_seconds,
            call_output=self._call_output,
            build_rotation_states=self._build_rotation_states,
            idle_source=idle_source,
        )
        self._alerts = AlertManager(alert_config or AlertConfig())
        self._last_alert_check: Optional[float] = None
        self._overrides = overrides

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

        now_playing = self._resolve_now_playing()
        if now_playing is None:
            self._handle_nothing_playing()
            return

        self._nothing_playing_since = None
        if now_playing.media_type == "music":
            now_playing.title = _strip_parenthetical(now_playing.title)
        self._maybe_clear_stale_idle_state(now_playing)

        transition = self._classify(now_playing)
        if transition is _Transition.SAME_ITEM_ROTATE:
            self._refresh_position(now_playing)
            self._maybe_rotate()
        elif transition is _Transition.SAME_ITEM_NO_ARTWORK:
            self._refresh_position(now_playing)
            # Same no-artwork item: keep idle wallpapers running on image
            # outputs without notifying text-only outputs to go idle.
            self._show_idle_wallpaper(notify_idle=False)
        else:
            self._handle_new_item(now_playing)

    def _refresh_position(self, now_playing: NowPlaying) -> None:
        """Keep self._current's playback position/duration fresh from
        every poll, not just frozen at whatever it was when the item
        started - _maybe_rotate periodically re-pushes self._current to
        outputs (see its docstring).
        """
        assert self._current is not None  # only called for SAME_ITEM transitions
        self._current.position_seconds = now_playing.position_seconds
        self._current.duration_seconds = now_playing.duration_seconds

    def _resolve_now_playing(self) -> Optional[NowPlaying]:
        """Poll sources and apply the Hitster-safe filter - the one
        decision that has to happen before we can compare against
        self._current, since it can turn a real poll result into "nothing
        playing".
        """
        now_playing = self._poll_sources()
        if (
            now_playing is not None
            and now_playing.media_type == "music"
            and self.get_hitster_safe()
        ):
            return None
        return now_playing

    def _maybe_clear_stale_idle_state(self, now_playing: NowPlaying) -> None:
        self._idle.clear_if_stale(now_playing)

    def _classify(self, now_playing: NowPlaying) -> _Transition:
        """Pure: decide what kind of tick this is from `now_playing` and
        `self._current` alone - no enrichment, no cache access, no output
        calls.
        """
        if self._current is not None and now_playing.identity == self._current.identity:
            return (
                _Transition.SAME_ITEM_ROTATE
                if self._current.images
                else _Transition.SAME_ITEM_NO_ARTWORK
            )
        return _Transition.NEW_ITEM

    def _handle_nothing_playing(self) -> None:
        if self._current is not None:
            now = time.monotonic()
            if self._nothing_playing_since is None:
                self._nothing_playing_since = now
            if now - self._nothing_playing_since < _NOTHING_PLAYING_GRACE_SECONDS:
                # Tolerate a brief gap without touching outputs at all - see
                # _NOTHING_PLAYING_GRACE_SECONDS above.
                return
            logger.info("Nothing playing; switching outputs to idle")
            self._current = None
            self._rotation_state = {}
            self._nothing_playing_since = None
        self._show_idle_wallpaper()

    def _handle_new_item(self, now_playing: NowPlaying) -> None:
        for enricher in self.enrichers:
            self._safe_call(enricher.enrich, now_playing)

        self._apply_artwork_override(now_playing)

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

    def _apply_artwork_override(self, now_playing: NowPlaying) -> None:
        """If a manual override is pinned for this title/subtitle (see
        artwork_overrides.py), replace whatever enrichment found with just
        that one image - a deliberate user choice overrides automatic
        enrichment entirely, rather than just joining the rotation pool.
        """
        if self._overrides is None:
            return
        try:
            override = self._overrides.get(now_playing.title, now_playing.subtitle)
        except Exception:
            logger.exception("Error checking artwork overrides for %s", now_playing.title)
            return
        if override is not None:
            now_playing.images = [override]

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
        """Advance (or, for a single-image item, simply re-push) each
        output's current pick once its rotation_interval_seconds elapses.

        Single-image items still go through this on schedule rather than
        being skipped entirely - a push that failed once (e.g. a physical
        display like a Pixoo64 being transiently unreachable) would
        otherwise never be retried for as long as that one item keeps
        playing, leaving the output frozen on whatever it last received
        (which could be a *previous*, unrelated item's artwork) until the
        next genuinely different item starts.
        """
        if self._current is None:
            return

        now = time.monotonic()
        multi_image = len(self._current.images) > 1
        for index, output in enumerate(self.outputs):
            state = self._rotation_state.get(index)
            if state is None or now - state.last_rotation < self.rotation_interval_seconds:
                continue

            if multi_image:
                state.position = (state.position + 1) % len(state.order)
            state.last_rotation = now
            self._show_image_for_output(index, output)

    def _show_image_for_output(self, index: int, output: Output) -> None:
        """Resolve and push the output's current rotation pick - falling
        through the rest of the pool (in rotation order) if that pick fails
        to fetch (e.g. rejected by the cache's minimum-size filter, or a
        download error), rather than leaving the output showing nothing
        until its next scheduled rotation, up to rotation_interval_seconds
        later.
        """
        assert self._current is not None  # only called while something is playing
        state = self._rotation_state[index]
        images = self._current.images
        tier: CacheTier = "music" if self._current.media_type == "music" else "default"

        for attempt in range(len(images)):
            artwork = images[state.order[(state.position + attempt) % len(state.order)]]
            try:
                image_path = self.cache.get_path(artwork, tier=tier)
                if image_path is None:
                    continue
                image_path = self.cache.get_transformed_path(image_path, output.transform_pipeline)
            except Exception:
                logger.exception("Failed to fetch artwork %s", artwork.url)
                continue

            self._call_output(index, output.update, self._current, artwork, image_path)
            return

        logger.warning(
            "No fetchable artwork for %s (%d candidate(s) all failed)",
            self._current.title, len(images),
        )

    def _show_idle_wallpaper(self, notify_idle: bool = True) -> None:
        """Show idle wallpapers on image-capable outputs.

        notify_idle controls whether on_idle() is called (set to False when
        something is playing but has no artwork, so outputs keep their current
        display instead of clearing).
        """
        self._idle.show(time.monotonic(), notify_idle=notify_idle)

    def _poll_sources(self) -> Optional[NowPlaying]:
        now = time.monotonic()
        for source in self.sources:
            name = getattr(source, "name", type(source).__name__)

            backoff = self._health.source_backoff.get(name)
            if backoff is not None and now < backoff.next_attempt:
                continue  # backing off: skip polling this source this tick

            self._health.record_poll(name, now)
            result = source.get_now_playing()

            if getattr(source, "last_poll_failed", False):
                self._health.record_backoff(name, self._next_backoff(backoff, now))
            elif backoff is not None:
                self._health.clear_backoff(name)

            if result is not None:
                self._health.set_active_source(name)
                return result
        self._health.set_active_source(None)
        return None

    def _next_backoff(self, previous: Optional["_BackoffState"], now: float) -> "_BackoffState":
        if previous is None:
            delay = self.backoff_initial_seconds
        else:
            delay = min(previous.delay * _BACKOFF_MULTIPLIER, self.backoff_max_seconds)
        return _BackoffState(delay=delay, next_attempt=now + delay)

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
        np = self._current
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
        data["idle_wallpapers_loaded"] = len(self._idle.images)
        data["hitster_safe"] = self.get_hitster_safe()
        return data
