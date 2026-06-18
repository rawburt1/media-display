"""Disk cache for downloaded artwork images."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse

import requests
from PIL import Image

from mediainfo.models import Artwork

logger = logging.getLogger(__name__)

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_DEFAULT_EXTENSION = ".jpg"


class ImageCache:
    """Downloads artwork once per URL and reuses the cached file afterwards."""

    def __init__(self, cache_dir: Union[str, Path], max_age_days: int = 30):
        # Resolve to an absolute path: Flask's send_file() resolves relative
        # paths against the app module's directory, not the cwd, so a
        # relative cache dir would point at the wrong location when serving
        # images.
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_seconds = max_age_days * 86400

    def get_path(self, artwork: Optional[Artwork]) -> Optional[Path]:
        """Return a local file path for the artwork, downloading it if needed.

        Returns None if there is no artwork (or its URL is empty).
        """
        if artwork is None or not artwork.url:
            return None

        # Local file written directly by a source (e.g. Apple TV artwork).
        if artwork.url.startswith("file://"):
            path = Path(urlparse(artwork.url).path)
            return path if path.exists() else None

        key = hashlib.sha256(artwork.url.encode("utf-8")).hexdigest()
        existing = self._find_existing(key)
        if existing is not None:
            return existing

        response = requests.get(artwork.url, timeout=10, auth=artwork.auth)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        extension = _EXTENSIONS.get(content_type, _DEFAULT_EXTENSION)

        path = self.cache_dir / f"{key}{extension}"
        path.write_bytes(response.content)
        logger.info("Cached artwork %r -> %s", artwork.label or artwork.url, path.name)
        return path

    def _find_existing(self, key: str) -> Optional[Path]:
        for path in self.cache_dir.glob(f"{key}.*"):
            return path
        return None

    def get_transformed_path(self, original_path: Path, transforms: list) -> Path:
        """Return a path to a transformed copy of the image.

        The result is cached on disk keyed by (original stem, pipeline hash)
        so the pipeline is only applied once per unique image+transform combo.
        Returns the original path unchanged when the pipeline is empty.
        """
        if not transforms:
            return original_path

        from mediainfo.transforms import pipeline_cache_key

        key = f"{original_path.stem}_{pipeline_cache_key(transforms)}"
        existing = self._find_existing(key)
        if existing is not None:
            return existing

        img = Image.open(original_path)
        for transform in transforms:
            img = transform.apply(img)

        out_path = self.cache_dir / f"{key}.jpg"
        img.convert("RGB").save(out_path, format="JPEG", quality=95)
        return out_path

    def purge_expired(self) -> None:
        """Delete cached files that haven't been (re)downloaded in
        max_age_days. Anything still in regular use is re-fetched on its
        next access, which refreshes its mtime.
        """
        cutoff = time.time() - self.max_age_seconds
        for path in self.cache_dir.iterdir():
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                logger.info("Purged expired cached artwork %s", path.name)
