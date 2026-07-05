"""Base class for idle wallpaper plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from mediainfo.models import Artwork


class IdleWallpaperSource(ABC):
    """Provides wallpapers to show on outputs while nothing is playing.

    Implementations must catch their own connection/network errors, log
    them, and return an empty list rather than raising, so a failing
    wallpaper source never breaks the polling loop.
    """

    # How often (in seconds) the orchestrator should fetch a fresh batch of
    # wallpapers. Each output then independently rotates through that batch
    # (in its own random order) using the top-level rotation_interval_seconds.
    rotation_interval_seconds: float

    # Registry key this idle source is known by (e.g. "local") - None (the
    # default) falls back to health.py deriving it from the class name
    # (see make_health_provider). Set explicitly by every built-in idle
    # source so that fallback only matters for third-party subclasses.
    name: Optional[str] = None

    # Optional: the config dataclass (from mediainfo.config) that
    # configures this idle source, for a plugin that wants to declare the
    # pairing itself rather than relying on registries.py's IDLE_CLASSES
    # and mediainfo.config's IDLE_CONFIG_TYPES staying in sync by registry
    # key alone. None (the default) means "not declared".
    config_class: Optional[type] = None

    # Optional free-form feature flags - not consumed anywhere yet; a hook
    # for future capability queries without another base-class change.
    capabilities: frozenset = frozenset()

    @abstractmethod
    def get_wallpapers(self) -> List[Artwork]:
        """Return a fresh batch of wallpapers, or [] if none are available."""

    def health_check(self) -> Optional[dict]:
        """Optional self-reported health detail. None (the default) means
        nothing extra to report."""
        return None

    def test_connection(self) -> Tuple[bool, str]:
        """Optional connectivity check. Default: not implemented - no
        config UI "test connection" dispatch exists yet for idle sources.
        """
        return False, "No connection test available for this plugin"
