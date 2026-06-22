"""Webhook alerting for persistent output failures.

Checked periodically from Orchestrator (see _maybe_check_alerts) - once an
output has been continuously failing for at least error_threshold_seconds,
a single webhook POST is sent so a real hardware/network problem (e.g. a
Pixoo64 or Nest Hub that's been unreachable for an hour) gets noticed
without anyone having to look at /health. Re-fires at most every
repeat_interval_seconds while the outage continues, and resets the moment
the output recovers - so a long-lived outage doesn't spam the webhook, but
also doesn't get silently forgotten about either.
"""

from __future__ import annotations

import logging
from typing import Dict

import requests

from mediainfo.config import AlertConfig

logger = logging.getLogger(__name__)


class AlertManager:
    def __init__(self, config: AlertConfig):
        self.config = config
        self._last_alerted: Dict[int, float] = {}

    def check(self, output_labels: Dict[int, str], error_since: Dict[int, float], now: float) -> None:
        """error_since: {output_index: time.monotonic() the output's
        current, still-ongoing error streak began} - see
        _HealthTracker.output_error_since. output_labels: {output_index:
        human-readable label} used in the alert message.
        """
        if not self.config.enabled or not self.config.webhook_url:
            return

        # Forget any output that's no longer failing, so a future outage
        # for it is treated as new (and alerted on its own schedule).
        for index in list(self._last_alerted):
            if index not in error_since:
                self._last_alerted.pop(index, None)

        for index, since in error_since.items():
            duration = now - since
            if duration < self.config.error_threshold_seconds:
                continue
            last_alerted = self._last_alerted.get(index)
            if last_alerted is not None and now - last_alerted < self.config.repeat_interval_seconds:
                continue
            self._send(output_labels.get(index, f"output #{index}"), duration)
            self._last_alerted[index] = now

    def _send(self, label: str, duration_seconds: float) -> None:
        minutes = int(duration_seconds // 60)
        try:
            requests.post(
                self.config.webhook_url,
                json={
                    "text": f"mediainfo: {label} has been failing for {minutes} minute(s)",
                    "output": label,
                    "duration_seconds": round(duration_seconds, 1),
                },
                timeout=10,
            )
            logger.info("Sent alert webhook for %s (failing %d minute(s))", label, minutes)
        except Exception:
            logger.exception("Failed to send alert webhook for %s", label)
