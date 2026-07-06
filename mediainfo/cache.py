"""Disk cache for downloaded artwork images."""

from __future__ import annotations

import hashlib
import io
import logging
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, Literal, Optional, Union
from urllib.parse import urlparse

import requests
from PIL import Image, UnidentifiedImageError

from mediainfo.models import Artwork

logger = logging.getLogger(__name__)

# Which cache subdirectory an image belongs in - "idle" and "music" get
# their own retention rules (see ImageCache.__init__); "default" is
# everything else (movie/TV posters and fanart).
CacheTier = Literal["default", "idle", "music"]

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_DEFAULT_EXTENSION = ".jpg"
# Some hosts (e.g. Wikimedia, used by the Wikipedia enricher) return 403 for
# the default python-requests User-Agent and require a descriptive one.
_HEADERS = {"User-Agent": "mediainfo/1.0 (+https://github.com/rawburt1/media-display)"}

# Default minimum dimensions - see ImageCache.__init__'s min_width/
# min_height params (configurable via CacheConfig.min_width/min_height).
_DEFAULT_MIN_WIDTH = 400
_DEFAULT_MIN_HEIGHT = 400


class ImageCache:
    """Downloads artwork once per URL and reuses the cached file afterwards."""

    def __init__(
        self,
        cache_dir: Union[str, Path],
        max_age_days: int = 30,
        idle_max_age_hours: int = 48,
        min_width: int = _DEFAULT_MIN_WIDTH,
        min_height: int = _DEFAULT_MIN_HEIGHT,
    ):
        # Resolve to an absolute path: Flask's send_file() resolves relative
        # paths against the app module's directory, not the cwd, so a
        # relative cache dir would point at the wrong location when serving
        # images.
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Idle wallpapers (Unsplash, Last.fm scrobble history, etc.) live in
        # their own subdirectory so they can be purged on a much shorter
        # schedule than now-playing artwork - they're decorative and easily
        # refetched, unlike artwork tied to a specific item.
        self.idle_dir = self.cache_dir / "idle"
        self.idle_dir.mkdir(parents=True, exist_ok=True)
        # Music artwork (album art, artist photos) lives here instead and is
        # never purged - re-fetching the same handful of albums/artists
        # every time they're replayed isn't worth it the way it is for the
        # much larger, ever-changing set of movie/TV posters and fanart.
        self.music_dir = self.cache_dir / "music"
        self.music_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_seconds = max_age_days * 86400
        self.idle_max_age_seconds = idle_max_age_hours * 3600
        self.min_width = min_width
        self.min_height = min_height
        self._tier_dirs: Dict[CacheTier, Path] = {
            "default": self.cache_dir,
            "idle": self.idle_dir,
            "music": self.music_dir,
        }

    def get_path(
        self, artwork: Optional[Artwork], tier: CacheTier = "default"
    ) -> Optional[Path]:
        """Return a local file path for the artwork, downloading it if needed.

        Returns None if there is no artwork (or its URL is empty). `tier`
        picks which cache subdirectory (and retention rule) it belongs to -
        "idle" for idle wallpapers, "music" for album art/artist photos
        (never purged - see `music_dir`), "default" for everything else.
        """
        if artwork is None or not artwork.url:
            return None

        # Local file written directly by a source (e.g. Apple TV artwork).
        if artwork.url.startswith("file://"):
            path = Path(urlparse(artwork.url).path)
            return path if path.exists() else None

        base_dir = self._tier_dirs[tier]
        key = hashlib.sha256(artwork.url.encode("utf-8")).hexdigest()
        existing = self._find_existing(key, base_dir)
        if existing is not None:
            return existing

        response = requests.get(artwork.url, timeout=10, auth=artwork.auth, headers=_HEADERS)
        response.raise_for_status()

        if not self._meets_minimum_size(response.content):
            logger.info(
                "Skipped artwork %r - smaller than %dx%d",
                artwork.label or artwork.url, self.min_width, self.min_height,
            )
            return None

        jpeg = self._as_jpeg(response.content)
        if jpeg is not None:
            path = base_dir / f"{key}.jpg"
            path.write_bytes(jpeg)
        else:
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            extension = _EXTENSIONS.get(content_type, _DEFAULT_EXTENSION)
            path = base_dir / f"{key}{extension}"
            path.write_bytes(response.content)
        logger.info("Cached artwork %r -> %s", artwork.label or artwork.url, path.name)
        return path

    @staticmethod
    def _as_jpeg(content: bytes) -> Optional[bytes]:
        """Return `content` as JPEG bytes, or None if it can't be decoded.

        Downloads are normalized to JPEG so the cache holds one predictable
        format regardless of what each source/enricher happens to serve
        (PNG, WebP, GIF, ...) - physical displays and their transform
        pipelines don't all handle every format equally well. Content
        that's already JPEG is stored byte-for-byte rather than re-encoded:
        recompressing an existing JPEG only loses quality and often grows
        the file. None (an undecodable payload) tells the caller to fall
        back to storing the raw bytes under a Content-Type-derived
        extension, the pre-normalization behavior.
        """
        try:
            img = Image.open(io.BytesIO(content))
            if img.format == "JPEG":
                return content
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=95)
            return buf.getvalue()
        except Exception:
            return None

    def _meets_minimum_size(self, content: bytes) -> bool:
        """True if the image meets the minimum dimensions, or if its size
        can't be determined (e.g. an unrecognized format) - this only ever
        rejects images we can positively confirm are too small.
        """
        if self.min_width <= 0 and self.min_height <= 0:
            return True
        try:
            with Image.open(io.BytesIO(content)) as img:
                width, height = img.size
        except (UnidentifiedImageError, OSError):
            return True
        return width >= self.min_width and height >= self.min_height

    @staticmethod
    def _find_existing(key: str, base_dir: Path) -> Optional[Path]:
        for path in base_dir.glob(f"{key}.*"):
            return path
        return None

    def download_temp(self, artwork: Optional[Artwork]) -> Optional[Path]:
        """Download artwork to a temporary file without writing to the cache.

        The caller is responsible for deleting the file when done. Returns None
        if there is no artwork, the URL is empty, or the image is smaller than
        the configured minimum dimensions. file:// URLs are returned as-is
        without downloading (caller must not delete those paths).
        """
        if artwork is None or not artwork.url:
            return None

        if artwork.url.startswith("file://"):
            path = Path(urlparse(artwork.url).path)
            return path if path.exists() else None

        response = requests.get(artwork.url, timeout=10, auth=artwork.auth, headers=_HEADERS)
        response.raise_for_status()

        if not self._meets_minimum_size(response.content):
            logger.info(
                "Skipped artwork %r - smaller than %dx%d",
                artwork.label or artwork.url, self.min_width, self.min_height,
            )
            return None

        jpeg = self._as_jpeg(response.content)
        if jpeg is not None:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                f.write(jpeg)
            return Path(f.name)
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        extension = _EXTENSIONS.get(content_type, _DEFAULT_EXTENSION)
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as f:
            f.write(response.content)
        return Path(f.name)

    def get_transformed_path(self, original_path: Path, transforms: list) -> Path:
        """Return a path to a transformed copy of the image.

        The result is cached on disk keyed by (original stem, pipeline hash)
        so the pipeline is only applied once per unique image+transform combo.
        Returns the original path unchanged when the pipeline is empty. The
        transformed copy is written alongside the original (idle, music, or
        regular), so it shares the same retention as the original.
        """
        if not transforms:
            return original_path

        from mediainfo.transforms import pipeline_cache_key

        base_dir = original_path.parent
        key = f"{original_path.stem}_{pipeline_cache_key(transforms)}"
        existing = self._find_existing(key, base_dir)
        if existing is not None:
            return existing

        img = Image.open(original_path)
        for transform in transforms:
            img = transform.apply(img)

        out_path = base_dir / f"{key}.jpg"
        img.convert("RGB").save(out_path, format="JPEG", quality=95)
        return out_path

    def get_derived_path(
        self,
        original_path: Path,
        cache_key: str,
        build: Callable[[Image.Image], Image.Image],
    ) -> Path:
        """Return a path to a derived image, built by `build` and cached on
        disk keyed by (original stem, cache_key) - same cache-hit scheme as
        get_transformed_path, but for callers whose derivation isn't a
        Transform pipeline (e.g. Pixoo's LED-preparation pipeline).

        Saved as PNG rather than JPEG: this is meant for small,
        palette-reduced pixel-art-style output, where JPEG's lossy 8x8 DCT
        blocks would smear a handful of exact colours together and
        reintroduce colours outside the reduced palette. `cache_key` should
        already reflect every setting that affects `build`'s output (plus a
        version marker for the build logic itself), since it's the sole
        cache-invalidation signal here.
        """
        base_dir = original_path.parent
        key = f"{original_path.stem}_{cache_key}"
        existing = self._find_existing(key, base_dir)
        if existing is not None:
            return existing

        image = build(Image.open(original_path))

        out_path = base_dir / f"{key}.png"
        image.save(out_path, format="PNG")
        return out_path

    def purge_expired(self) -> None:
        """Delete cached files past their retention window. Anything still
        in regular use is re-fetched on its next access, which refreshes its
        mtime, so this only ever removes genuinely stale files.

        music_dir is deliberately not purged here - see its docstring above.
        """
        self._purge_dir(self.cache_dir, self.max_age_seconds)
        self._purge_dir(self.idle_dir, self.idle_max_age_seconds)

    @staticmethod
    def _purge_dir(dir_path: Path, max_age_seconds: float) -> None:
        cutoff = time.time() - max_age_seconds
        for path in dir_path.iterdir():
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                logger.info("Purged expired cached artwork %s", path.name)
