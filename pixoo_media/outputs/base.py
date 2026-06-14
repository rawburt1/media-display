"""Base class for output plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pixoo_media.models import Artwork, NowPlaying


class Output(ABC):
    """Something that displays the current "now playing" artwork."""

    @abstractmethod
    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        """Show new artwork."""

    def on_idle(self) -> None:
        """Called once when nothing is playing. Default: do nothing."""
