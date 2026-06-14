"""Disk cache for downloaded artwork images."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional, Union

import requests

from pixoo_media.models import Artwork

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

    def __init__(self, cache_dir: Union[str, Path]):
        # Resolve to an absolute path: Flask's send_file() resolves relative
        # paths against the app module's directory, not the cwd, so a
        # relative cache dir would point at the wrong location when serving
        # images.
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_path(self, artwork: Optional[Artwork]) -> Optional[Path]:
        """Return a local file path for the artwork, downloading it if needed.

        Returns None if there is no artwork (or its URL is empty).
        """
        if artwork is None or not artwork.url:
            return None

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
