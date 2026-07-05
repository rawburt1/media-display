"""Local-folder idle wallpaper source.

Treats each immediate subdirectory of `dir` as one "destination" (e.g. one
folder per trip/location). Each batch picks ONE destination at random and
returns up to `batch_size` random pictures from within it (searched
recursively, so a destination's own subfolders are included too) -
pictures from different destinations are never mixed within the same
batch, matching how the other idle sources are kept from mixing with each
other (see idle/composite.py).

No network/download involved - returned as file:// URLs, which
ImageCache.get_path() already serves directly without downloading or
running through the minimum-size filter (see cache.py), the same way
local Apple TV artwork is served.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import List

from mediainfo.config import LocalWallpaperConfig
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import Artwork

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


class LocalWallpaperSource(IdleWallpaperSource):
    name = "local"

    def __init__(self, config: LocalWallpaperConfig):
        self.config = config
        self.rotation_interval_seconds = config.rotation_interval_seconds
        self.base_dir = Path(config.dir)

    def get_wallpapers(self) -> List[Artwork]:
        try:
            destinations = [p for p in self.base_dir.iterdir() if p.is_dir()]
        except OSError:
            logger.exception("Failed to list local wallpaper destinations under %s", self.base_dir)
            return []

        if not destinations:
            logger.warning("No destination folders found under %s", self.base_dir)
            return []

        destination = random.choice(destinations)
        try:
            images = [
                path
                for path in destination.rglob("*")
                if path.is_file() and path.suffix.lower() in _IMAGE_EXTENSIONS
            ]
        except OSError:
            logger.exception("Failed to list pictures in destination %s", destination)
            return []

        if not images:
            logger.warning("No pictures found in destination %s", destination)
            return []

        chosen = random.sample(images, min(self.config.batch_size, len(images)))
        logger.info(
            "Local: picked %d picture(s) from destination %r", len(chosen), destination.name
        )
        return [
            Artwork(url=f"file://{path.resolve()}", label=f"{destination.name}: {path.stem}")
            for path in chosen
        ]
