"""Base class for media source plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from pixoo_media.models import NowPlaying


class MediaSource(ABC):
    """A pollable source of "now playing" information.

    Implementations must catch their own connection/network errors, log
    them, and return None rather than raising, so that one unreachable
    source never breaks the polling loop.
    """

    name: str

    @abstractmethod
    def get_now_playing(self) -> Optional[NowPlaying]:
        """Return the current snapshot, or None if nothing is active."""
