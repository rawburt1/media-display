"""Base class for media source plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Tuple

from mediainfo.models import NowPlaying


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

    def test_connection(self) -> Tuple[bool, str]:
        """Optional connectivity check for the config UI's "test
        connection" button. Default: not implemented here - today this is
        instead dispatched by name in
        mediainfo/outputs/config_dashboard.py (test_source()); migrating
        an individual plugin's test logic to this method is a reasonable
        future increment, one plugin at a time, rather than all at once.
        """
        return False, "No connection test available for this plugin"
