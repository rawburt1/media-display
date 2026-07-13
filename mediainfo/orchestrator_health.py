"""Runtime health-tracking state backing Orchestrator.get_health() - source
polling/backoff and output error bookkeeping.

Split out of orchestrator.py: grouped here instead of as five separate
Orchestrator attributes, so get_health() has one thing to query and
Orchestrator.__init__ has one thing to set up.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Dict, Optional, Tuple


@dataclasses.dataclass
class _BackoffState:
    delay: float
    next_attempt: float


class _HealthTracker:
    def __init__(self) -> None:
        self.start_time = time.monotonic()
        self.active_source_name: Optional[str] = None
        # When the poll loop last completed one full iteration (including
        # its own error handling) - None until the very first one. Read by
        # a separate supervisor thread (Orchestrator._supervise) that has
        # no other way to notice a stuck/dead poll loop, since a hung
        # _tick() call never returns control to _run() to update anything
        # itself. See seconds_since_last_tick in /health.
        self.last_tick_at: Optional[float] = None
        self.source_polled: Dict[str, float] = {}
        self.source_backoff: Dict[str, _BackoffState] = {}
        # When the current (still-ongoing) failure streak for a source
        # began - same "set once, left untouched by subsequent failures,
        # cleared on recovery" discipline as output_error_since. Used by
        # alerting.AlertManager.
        self.source_error_since: Dict[str, float] = {}
        self.output_errors: Dict[int, Tuple[str, float]] = {}
        # When the current (still-ongoing) error streak for an output
        # began - set once on the first error and left untouched by
        # subsequent ones, so it reflects how long the output has been
        # continuously failing rather than just the most recent failure.
        # Used by alerting.AlertManager. Cleared on recovery.
        self.output_error_since: Dict[int, float] = {}

    def record_tick(self, now: float) -> None:
        self.last_tick_at = now

    def record_poll(self, name: str, now: float) -> None:
        self.source_polled[name] = now

    def set_active_source(self, name: Optional[str]) -> None:
        self.active_source_name = name

    def record_backoff(self, name: str, state: _BackoffState, now: float) -> None:
        self.source_backoff[name] = state
        self.source_error_since.setdefault(name, now)

    def clear_backoff(self, name: str) -> None:
        self.source_backoff.pop(name, None)
        self.source_error_since.pop(name, None)

    def record_output_success(self, index: int) -> None:
        self.output_errors.pop(index, None)
        self.output_error_since.pop(index, None)

    def record_output_error(self, index: int, message: str, now: float) -> None:
        self.output_errors[index] = (message[:300], now)
        self.output_error_since.setdefault(index, now)

    def as_dict(self, now: float) -> dict:
        return {
            "uptime_seconds": round(now - self.start_time, 1),
            "seconds_since_last_tick": (
                round(now - self.last_tick_at, 1) if self.last_tick_at is not None else None
            ),
            "active_source": self.active_source_name,
            "source_last_polled_ago": {
                name: round(now - ts, 1) for name, ts in self.source_polled.items()
            },
            "source_backoff_seconds": {
                name: round(max(state.next_attempt - now, 0), 1)
                for name, state in self.source_backoff.items()
            },
            "source_failing_for_seconds": {
                name: round(now - since, 1) for name, since in self.source_error_since.items()
            },
            "output_errors": {
                i: {
                    "message": msg,
                    "ago_seconds": round(now - ts, 1),
                    "failing_for_seconds": round(now - self.output_error_since.get(i, ts), 1),
                }
                for i, (msg, ts) in self.output_errors.items()
            },
        }
