"""Folder output: mirrors the current item's artwork to a local folder."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from mediainfo.cache import CacheTier, ImageCache
from mediainfo.config import FolderConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output
from mediainfo.transforms import parse_pipeline

logger = logging.getLogger(__name__)

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class FolderOutput(Output):
    """Mirrors all artwork (album art, fanart, posters) for the currently
    playing item into a local folder, e.g. for a digital photo frame or
    other tool that just reads "whatever's in this folder".

    The folder always reflects only the current item: its contents are
    replaced whenever the item changes. While idle, it instead mirrors the
    whole batch of idle wallpapers, replaced whenever a new batch is
    fetched; it's cleared only when no idle wallpapers are available.
    """

    name = "folder"
    config_class = FolderConfig

    def __init__(self, config: FolderConfig):
        self.config = config
        self.dir = Path(config.dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.transform_pipeline = parse_pipeline(config.transforms)

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        pass

    def on_idle(self) -> None:
        self._clear()

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        self._clear()
        idle = now_playing.source == "idle"
        tier: CacheTier = (
            "idle" if idle else "music" if now_playing.media_type == "music" else "default"
        )

        for artwork in now_playing.images:
            try:
                src = cache.get_path(artwork, tier=tier)
                if src is None:
                    continue
                src = cache.get_transformed_path(src, self.transform_pipeline)
            except Exception:
                logger.exception("Failed to fetch artwork %s", artwork.url)
                continue

            dest = self.dir / self._filename(artwork, src.suffix, idle=idle)
            try:
                shutil.copyfile(src, dest)
            except OSError:
                logger.exception("Failed to copy artwork to %s", dest)

    def _clear(self) -> None:
        for path in self.dir.iterdir():
            if path.is_file():
                try:
                    path.unlink()
                except OSError:
                    logger.exception("Failed to remove %s", path)

    @staticmethod
    def _filename(artwork: Artwork, extension: str, idle: bool = False) -> str:
        name = _INVALID_CHARS.sub("_", artwork.label or "image").strip()
        prefix = "idle_" if idle else ""
        return f"{prefix}{name}{extension}"
