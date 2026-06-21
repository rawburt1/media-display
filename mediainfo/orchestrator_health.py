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
        self.source_polled: Dict[str, float] = {}
        self.source_backoff: Dict[str, _BackoffState] = {}
        self.output_errors: Dict[int, Tuple[str, float]] = {}

    def record_poll(self, name: str, now: float) -> None:
        self.source_polled[name] = now

    def set_active_source(self, name: Optional[str]) -> None:
        self.active_source_name = name

    def record_backoff(self, name: str, state: _BackoffState) -> None:
        self.source_backoff[name] = state

    def clear_backoff(self, name: str) -> None:
        self.source_backoff.pop(name, None)

    def record_output_success(self, index: int) -> None:
        self.output_errors.pop(index, None)

    def record_output_error(self, index: int, message: str, now: float) -> None:
        self.output_errors[index] = (message[:300], now)

    def as_dict(self, now: float) -> dict:
        return {
            "uptime_seconds": round(now - self.start_time, 1),
            "active_source": self.active_source_name,
            "source_last_polled_ago": {
                name: round(now - ts, 1) for name, ts in self.source_polled.items()
            },
            "source_backoff_seconds": {
                name: round(max(state.next_attempt - now, 0), 1)
                for name, state in self.source_backoff.items()
            },
            "output_errors": {
                i: {"message": msg, "ago_seconds": round(now - ts, 1)}
                for i, (msg, ts) in self.output_errors.items()
            },
        }
