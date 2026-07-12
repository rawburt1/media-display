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

    # Optional free-form feature flags. wiring.build_idle_source() reads
    # "library" off this to decide whether to pass the shared MusicLibrary -
    # see LibraryWallpaperSource. Empty (the default) means no extra
    # argument.
    capabilities: frozenset = frozenset()

    # List of Transform objects applied to every picture from this source
    # specifically, before any per-output transform pipeline - lets one
    # idle source have its own look (crop/filter/...) independent of other
    # idle sources and outputs. Empty (the default) means no source-level
    # styling, exactly today's behavior. Populated from the source's own
    # config `transforms:` key, mirroring Output.transform_pipeline - see
    # mediainfo.orchestrator_idle._IdleBatchManager for where it's combined
    # with the destination output's own pipeline.
    transform_pipeline: List = []

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
