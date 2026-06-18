"""Base class for media source plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

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

    @abstractmethod
    def get_now_playing(self) -> Optional[NowPlaying]:
        """Return the current snapshot, or None if nothing is active."""
