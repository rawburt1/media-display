"""Base class for idle wallpaper plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from pixoo_media.models import Artwork


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

    @abstractmethod
    def get_wallpapers(self) -> List[Artwork]:
        """Return a fresh batch of wallpapers, or [] if none are available."""
