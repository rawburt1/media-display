"""Base class for idle wallpaper plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from pixoo_media.models import Artwork


class IdleWallpaperSource(ABC):
    """Provides wallpapers to show on outputs while nothing is playing.

    Implementations must catch their own connection/network errors, log
    them, and return None rather than raising, so a failing wallpaper
    source never breaks the polling loop.
    """

    # How often (in seconds) the orchestrator should ask for a new wallpaper.
    rotation_interval_seconds: float

    @abstractmethod
    def get_wallpaper(self) -> Optional[Artwork]:
        """Return a new wallpaper, or None if none is available right now."""
