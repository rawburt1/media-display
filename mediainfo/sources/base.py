"""Base class for media source plugins."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional, Tuple

from mediainfo.models import NowPlaying
from mediainfo.status import AvailabilityReason


class MediaSource(ABC):
    """A pollable source of "now playing" information.

    Implementations must catch their own connection/network errors, log
    them, and return None rather than raising, so that one unreachable
    source never breaks the polling loop.
    """

    name: str

    # Set this to True at the point get_now_playing() returns None because
    # the device/service couldn't be reached (vs. False - the default -
    # when it connected fine and simply has nothing active). The
    # orchestrator uses this to back off polling frequency for sources
    # whose device is unreachable, without delaying detection for sources
    # that are just legitimately idle.
    last_poll_failed: bool = False

    # Optional, finer-grained companion to last_poll_failed - lets a
    # source distinguish *why* it can't currently report state (device
    # off vs. a real integration error) instead of the flat boolean, so
    # the config UI's Health/Activity model (see mediainfo/status.py) can
    # show a powered-off device as healthy-but-sleeping rather than
    # broken. None (the default) means "this source hasn't been migrated
    # to the richer model yet" - callers fall back to deriving a reason
    # from last_poll_failed alone, so an unmigrated source's behavior is
    # unchanged.
    availability_reason: Optional[AvailabilityReason] = None

    # Optional: the config dataclass (from mediainfo.config) that
    # configures this source, for a plugin that wants to declare the
    # pairing itself rather than relying on registries.py's SOURCE_CLASSES
    # and mediainfo.config's SOURCE_CONFIG_TYPES staying in sync by
    # registry key alone. None (the default) means "not declared".
    config_class: Optional[type] = None

    # Optional free-form feature flags (e.g. "multi_instance") - not
    # consumed anywhere yet; a hook for future capability queries without
    # another base-class change.
    capabilities: frozenset = frozenset()

    @abstractmethod
    def get_now_playing(self) -> Optional[NowPlaying]:
        """Return the current snapshot, or None if nothing is active."""

    def health_check(self) -> Optional[dict]:
        """Optional self-reported health detail beyond what the
        orchestrator already tracks generically (poll timing,
        backoff/last_poll_failed - see orchestrator_health.py). None (the
        default) means nothing extra to report.
        """
        return None

    def log_poll_error(self, log: logging.Logger, msg: str, *args: object) -> None:
        """Call from an except block instead of log.exception() directly,
        wherever a poll failure that sets last_poll_failed gets logged -
        logs the first failure in a streak at ERROR (with traceback), then
        downgrades repeats to DEBUG (still with the traceback, so it's
        still there for anyone who turns DEBUG logging on) until
        note_poll_recovered() is called. Otherwise an offline device
        produces one ERROR-with-traceback per backoff retry for as long as
        it stays offline - could be hours (M8 in
        docs/architecture-usability-review-2026-07.md).
        """
        self._consecutive_poll_failures = getattr(self, "_consecutive_poll_failures", 0) + 1
        level = logging.ERROR if self._consecutive_poll_failures == 1 else logging.DEBUG
        log.log(level, msg, *args, exc_info=True)

    def note_poll_recovered(self) -> None:
        """Reset the failure streak log_poll_error tracks, so the next
        failure (a fresh outage, not a continuation of the old one) logs
        at ERROR again instead of staying downgraded to DEBUG forever.
        Called by _SourcePoller after every poll that isn't currently
        failing - a source with its own separate reconnect loop (see
        HomeAssistantSource) calls this itself instead, at its own
        "connected again" checkpoint.
        """
        self._consecutive_poll_failures = 0

    def test_connection(self) -> Tuple[bool, str]:
        """Connectivity check for the config UI's "test connection"
        button: poll once via the real get_now_playing() - the same call
        the orchestrator itself makes every tick, so there's no separate
        test code path to fall out of sync with real polling. This one
        implementation covers every source uniformly; a plugin needing
        extra cleanup around it (e.g. AppleTvSource's background asyncio
        loop) should override this and delegate back via super()."""
        try:
            result = self.get_now_playing()
            if self.last_poll_failed:
                return False, "Could not connect - check host/credentials"
            if result is not None:
                return True, f"Connected - currently playing: {result.title}"
            return True, "Connected - nothing currently playing"
        except Exception as exc:
            return False, f"Error: {exc}"
