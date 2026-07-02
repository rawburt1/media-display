"""Base class for output plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from mediainfo.cache import ImageCache
from mediainfo.models import Artwork, NowPlaying


class Output(ABC):
    """Something that displays the current "now playing" artwork."""

    # Set to False on text-only outputs (e.g. Ulanzi) so that idle wallpaper
    # images are not routed to them.
    handles_images: bool = True

    # Set to True (e.g. on PixooOutput) to skip artist-photo images
    # (Artwork.is_artist_photo) while showing music, so this output only
    # ever shows actual album/cover art - never an unrelated artist bio
    # photo from the rotation pool. No effect outside music, since
    # artist photos only ever get added for media_type == "music".
    music_album_art_only: bool = False

    # List of Transform objects applied to every image before update() is
    # called.  Populated from the output's config `transforms:` key.
    transform_pipeline: List = []

    @abstractmethod
    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        """Show new artwork."""

    def on_idle(self) -> None:
        """Called once when nothing is playing. Default: do nothing."""

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        """Called once when the playing item changes, with access to all of
        its available images (not just the one currently shown/rotated).
        Default: do nothing.
        """

    def on_schedule_tick(self) -> None:
        """Called every orchestrator poll tick, regardless of what's
        playing or whether this output is filtered - the hook for
        time-based device housekeeping like power/brightness scheduling
        (see display_schedule.py). Implementations must be cheap when
        nothing needs doing and must not raise. Default: do nothing.
        """
