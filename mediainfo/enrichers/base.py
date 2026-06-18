"""Base class for artwork enricher plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod

from mediainfo.models import NowPlaying


class ArtworkEnricher(ABC):
    """Adds extra Artwork entries to a NowPlaying's `images` list.

    Implementations must catch their own connection/network errors, log
    them, and leave `now_playing.images` unchanged on failure, so one
    unreachable enricher never breaks the polling loop.
    """

    @abstractmethod
    def enrich(self, now_playing: NowPlaying) -> None:
        """Mutate `now_playing.images` in place, appending any extra art."""
