"""Webhook alerting for persistent source or output failures.

Checked periodically from Orchestrator (see _maybe_check_alerts) - once a
source or output has been continuously failing for at least
error_threshold_seconds, a single webhook POST is sent so a real hardware/
network problem (e.g. a Pixoo64/Nest Hub that's unreachable, or a source
like vinyl_recognizer that's simply not running) gets noticed without
anyone having to look at /health. Re-fires at most every
repeat_interval_seconds while the outage continues, and resets the moment
it recovers - so a long-lived outage doesn't spam the webhook, but also
doesn't get silently forgotten about either.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

from mediainfo.config import AlertConfig

logger = logging.getLogger(__name__)


class AlertManager:
    def __init__(self, config: AlertConfig):
        self.config = config
        self._last_alerted_outputs: Dict[int, float] = {}
        self._last_alerted_sources: Dict[str, float] = {}

    def check(
        self,
        output_labels: Dict[int, str],
        output_error_since: Dict[int, float],
        now: float,
        source_error_since: Optional[Dict[str, float]] = None,
    ) -> None:
        """output_error_since: {output_index: time.monotonic() the
        output's current, still-ongoing error streak began} - see
        _HealthTracker.output_error_since. output_labels: {output_index:
        human-readable label} used in the alert message. source_error_since:
        the same concept for sources (see _HealthTracker.source_error_since)
        - sources need no separate labels dict, since they're already keyed
        by their own human-readable name.
        """
        if not self.config.enabled or not self.config.webhook_url:
            return

        self._check_category(self._last_alerted_outputs, output_error_since, output_labels, now, "output")
        source_error_since = source_error_since or {}
        source_labels = {name: name for name in source_error_since}
        self._check_category(self._last_alerted_sources, source_error_since, source_labels, now, "source")

    def _check_category(
        self,
        last_alerted: Dict[Any, float],
        error_since: Dict[Any, float],
        labels: Dict[Any, str],
        now: float,
        kind: str,
    ) -> None:
        # Forget any key that's no longer failing, so a future outage for
        # it is treated as new (and alerted on its own schedule).
        for key in list(last_alerted):
            if key not in error_since:
                last_alerted.pop(key, None)

        for key, since in error_since.items():
            duration = now - since
            if duration < self.config.error_threshold_seconds:
                continue
            previous = last_alerted.get(key)
            if previous is not None and now - previous < self.config.repeat_interval_seconds:
                continue
            self._send(kind, labels.get(key, f"{kind} #{key}"), duration)
            last_alerted[key] = now

    def _send(self, kind: str, label: str, duration_seconds: float) -> None:
        minutes = int(duration_seconds // 60)
        try:
            requests.post(
                self.config.webhook_url,
                json={
                    "text": f"mediainfo: {label} has been failing for {minutes} minute(s)",
                    "kind": kind,
                    kind: label,
                    "duration_seconds": round(duration_seconds, 1),
                },
                timeout=10,
            )
            logger.info("Sent alert webhook for %s (failing %d minute(s))", label, minutes)
        except Exception:
            logger.exception("Failed to send alert webhook for %s", label)
