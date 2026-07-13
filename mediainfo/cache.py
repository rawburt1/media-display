"""Disk cache for downloaded artwork images."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, Literal, Optional, Union
from urllib.parse import urlparse

import requests
from PIL import Image, UnidentifiedImageError

from mediainfo.disk_eviction import EvictionUnit, evict_by_size
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

# Default cap for the "music" tier (never purged by age - see
# ImageCache.__init__'s music_dir comment) - a few thousand cached album
# art + artist photo images, generous for a typical home library while
# still bounded (M2 in docs/architecture-usability-review-2026-07.md).
_DEFAULT_MAX_MUSIC_MB = 500


def flatten_transparency(img: Image.Image, background: str = "white") -> Image.Image:
    """Convert `img` to RGB, compositing onto `background` first if it has
    an alpha channel.

    A naive `img.convert("RGB")` discards alpha but keeps whatever RGB
    values were stored underneath it - many PNG encoders zero those out
    for fully-transparent pixels (a very common pattern for e.g. Wikipedia/
    Wikimedia thumbnails: an opaque subject on an otherwise fully
    transparent background). Left uncorrected, that turns into a mostly or
    entirely *black* image once flattened, cropped, and downscaled -
    exactly the "just a black picture" symptom this fixes.
    """
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        flattened = Image.new("RGB", rgba.size, background)
        flattened.paste(rgba, mask=rgba.split()[3])
        return flattened
    return img.convert("RGB")


class ImageCache:
    """Downloads artwork once per URL and reuses the cached file afterwards."""

    def __init__(
        self,
        cache_dir: Union[str, Path],
        max_age_days: int = 30,
        idle_max_age_hours: int = 48,
        min_width: int = _DEFAULT_MIN_WIDTH,
        min_height: int = _DEFAULT_MIN_HEIGHT,
        max_music_mb: Optional[int] = _DEFAULT_MAX_MUSIC_MB,
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
        # never purged *by age* - re-fetching the same handful of albums/
        # artists every time they're replayed isn't worth it the way it is
        # for the much larger, ever-changing set of movie/TV posters and
        # fanart. It's still bounded by total size (see
        # _evict_music_by_size/max_music_mb) - a slowly-growing library on
        # a small device (a Pi) would otherwise fill the disk over years.
        self.music_dir = self.cache_dir / "music"
        self.music_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_seconds = max_age_days * 86400
        self.idle_max_age_seconds = idle_max_age_hours * 3600
        self.min_width = min_width
        self.min_height = min_height
        self.max_music_bytes = max_music_mb * 1024 * 1024 if max_music_mb else None
        self._tier_dirs: Dict[CacheTier, Path] = {
            "default": self.cache_dir,
            "idle": self.idle_dir,
            "music": self.music_dir,
        }

    def get_path(self, artwork: Optional[Artwork], tier: CacheTier = "default") -> Optional[Path]:
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
            # Bump mtime on every hit, not just on a fresh download - the
            # "music" tier's size-capped eviction (see _evict_music_by_size)
            # needs a real last-used signal to evict correctly, and this
            # also makes the "still in regular use" mtime-refresh
            # purge_expired()'s own docstring already promises for the
            # other tiers actually true (M2 in
            # docs/architecture-usability-review-2026-07.md).
            existing.touch()
            return existing

        headers = {**_HEADERS, **artwork.headers} if artwork.headers else _HEADERS
        response = requests.get(artwork.url, timeout=10, auth=artwork.auth, headers=headers)
        response.raise_for_status()

        if not response.content:
            # A 200 with an empty body isn't a real image - if this were
            # written to disk it'd become a permanent 0-byte cache entry
            # (see _find_existing: any file matching the key is treated as
            # a hit forever), so every future lookup would keep "finding"
            # unreadable artwork instead of retrying the download.
            logger.warning(
                "Empty response downloading artwork %r - not caching", artwork.label or artwork.url
            )
            return None

        if not self._meets_minimum_size(response.content):
            logger.info(
                "Skipped artwork %r - smaller than %dx%d",
                artwork.label or artwork.url,
                self.min_width,
                self.min_height,
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
            flatten_transparency(img).save(buf, format="JPEG", quality=95)
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

        headers = {**_HEADERS, **artwork.headers} if artwork.headers else _HEADERS
        response = requests.get(artwork.url, timeout=10, auth=artwork.auth, headers=headers)
        response.raise_for_status()

        if not response.content:
            logger.warning(
                "Empty response downloading artwork %r - not caching", artwork.label or artwork.url
            )
            return None

        if not self._meets_minimum_size(response.content):
            logger.info(
                "Skipped artwork %r - smaller than %dx%d",
                artwork.label or artwork.url,
                self.min_width,
                self.min_height,
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
        flatten_transparency(img).save(out_path, format="JPEG", quality=95)
        return out_path

    def get_derived_path(
        self,
        original_path: Path,
        cache_key: str,
        build: Callable[[Image.Image], Union[Image.Image, tuple]],
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

        `build` may return either an Image, or an `(Image, metadata)` tuple
        where `metadata` is a JSON-serialisable dict (or None) - when a dict
        is given, it's written alongside the image as a `{key}.json`
        sidecar (e.g. Pixoo's text-removal decision record). Only written
        once, at build time - a cache hit skips `build` entirely and simply
        reuses whatever sidecar (if any) was written the first time.
        """
        base_dir = original_path.parent
        key = f"{original_path.stem}_{cache_key}"
        existing = self._find_existing(key, base_dir)
        if existing is not None:
            existing.touch()  # see get_path()'s matching comment
            return existing

        result = build(Image.open(original_path))
        if isinstance(result, tuple):
            image, metadata = result
        else:
            image, metadata = result, None

        out_path = base_dir / f"{key}.png"
        image.save(out_path, format="PNG")
        if metadata is not None:
            (base_dir / f"{key}.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return out_path

    def purge_expired(self) -> None:
        """Delete cached files past their retention window. Anything still
        in regular use is re-fetched on its next access, which refreshes its
        mtime, so this only ever removes genuinely stale files.

        music_dir is deliberately not age-purged here - see its docstring
        above - but is still swept for a total-size cap (see
        _evict_music_by_size).
        """
        self._purge_dir(self.cache_dir, self.max_age_seconds)
        self._purge_dir(self.idle_dir, self.idle_max_age_seconds)
        self._evict_music_by_size()

    @staticmethod
    def _purge_dir(dir_path: Path, max_age_seconds: float) -> None:
        cutoff = time.time() - max_age_seconds
        for path in dir_path.iterdir():
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                logger.info("Purged expired cached artwork %s", path.name)

    def _evict_music_by_size(self) -> None:
        """Size-capped LRU eviction for music_dir (M2 in
        docs/architecture-usability-review-2026-07.md) - a backstop against
        unbounded growth, independent of (and much coarser-grained than)
        the age-based purge every other tier gets, since music content is
        deliberately kept regardless of age. No-op if max_music_bytes is
        None (max_music_mb: 0/null in config - uncapped, the old
        "never purged" behavior).
        """
        if self.max_music_bytes is None:
            return
        units = [
            EvictionUnit(path=path, last_used=path.stat().st_mtime, size_bytes=path.stat().st_size)
            for path in self.music_dir.iterdir()
            if path.is_file()
        ]
        deleted = evict_by_size(units, self.max_music_bytes, delete=lambda p: p.unlink())
        for path in deleted:
            logger.info("Evicted least-recently-used music artwork %s (size cap)", path.name)
