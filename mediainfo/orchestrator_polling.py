"""Source polling: picks the highest-priority active source per route
group, respecting hitster-safe mode and per-source backoff.

Split out of orchestrator.py - holds no state of its own beyond backoff
tuning. `sources` and `groups` are passed into poll() on every call rather
than captured once at construction, because `Orchestrator.sources` can be
reassigned after construction (see tests) and the very next poll must see
the new list immediately.
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional

from mediainfo.models import NowPlaying
from mediainfo.orchestrator_health import _BackoffState, _HealthTracker
from mediainfo.orchestrator_state import _RouteGroup
from mediainfo.sources.base import MediaSource

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


def _group_accepts(group: _RouteGroup, item: NowPlaying) -> bool:
    """Whether `item` could be this group's current item - its
    content-rule signature alone; active_hours is applied per output at
    display time (see _compute_filtered/_recheck_filters)."""
    return group.signature.accepts(item)


class _SourcePoller:
    def __init__(
        self,
        health: _HealthTracker,
        get_hitster_safe: Callable[[], bool],
        backoff_initial_seconds: float,
        backoff_max_seconds: float,
    ):
        self._health = health
        self._get_hitster_safe = get_hitster_safe
        self.backoff_initial_seconds = backoff_initial_seconds
        self.backoff_max_seconds = backoff_max_seconds

    def poll(self, sources: List[MediaSource], groups: List[_RouteGroup]) -> List[NowPlaying]:
        """Poll sources in priority order, collecting the active results
        the route groups need, highest priority first.

        Polling stops as soon as every group is satisfied by something
        already collected - with a single unfiltered group that means the
        first active source, exactly the pre-routing behavior. Sources
        that are idle or backed off never block a lower-priority source
        from being offered to the groups.

        Hitster-safe applies here, per result: while enabled, a music
        result is discarded outright - it isn't offered to any group and
        doesn't satisfy one - so song titles never leak onto a display,
        while a lower-priority non-music item (e.g. a movie) can still
        show.
        """
        now = time.monotonic()
        results: List[NowPlaying] = []
        active_source_name: Optional[str] = None
        unsatisfied = list(groups)
        for source in sources:
            if not unsatisfied:
                break
            name = getattr(source, "name", type(source).__name__)

            backoff = self._health.source_backoff.get(name)
            if backoff is not None and now < backoff.next_attempt:
                continue  # backing off: skip polling this source this tick

            self._health.record_poll(name, now)
            result = source.get_now_playing()

            if getattr(source, "last_poll_failed", False):
                self._health.record_backoff(name, self._next_backoff(backoff, now), now)
            elif backoff is not None:
                self._health.clear_backoff(name)

            if result is None:
                continue
            if result.media_type == "music" and self._get_hitster_safe():
                continue
            if active_source_name is None:
                active_source_name = name
            results.append(result)
            unsatisfied = [g for g in unsatisfied if not _group_accepts(g, result)]

        self._health.set_active_source(active_source_name)
        return results

    def _next_backoff(self, previous: Optional["_BackoffState"], now: float) -> "_BackoffState":
        if previous is None:
            delay = self.backoff_initial_seconds
        else:
            delay = min(previous.delay * _BACKOFF_MULTIPLIER, self.backoff_max_seconds)
        return _BackoffState(delay=delay, next_attempt=now + delay)
