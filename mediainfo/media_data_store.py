"""Unified on-disk media metadata/artwork/lyrics cache: one human-browsable
folder per movie/series/album (e.g. `movies/Alien (1979)/poster.jpg`), each
with a `metadata.json` tracking where each piece of content came from and
when it was last checked/updated.

Foundation only - not yet wired into the live orchestrator/enrichment
pipeline. Existing `mediainfo.cache.ImageCache` (flat, hash-named artwork
cache), `mediainfo.text_cache.TextCache` (namespaced lyrics/AI-text cache),
`mediainfo.poster_store.PosterStore`, and `mediainfo.artwork_overrides.
ArtworkOverrideStore` are untouched and keep working exactly as before;
nothing here replaces or migrates them yet. `_fetch_*` methods are explicit
stubs (return None) - calling real APIs (TMDB/fanart.tv/MusicBrainz/discogs/
LRCLIB) is separate future work, once this store's cache/refresh mechanics
are proven out.

Directory layout:
    {path}/movies/{Title} ({Year})/poster.jpg
    {path}/movies/{Title} ({Year})/fanart.jpg
    {path}/movies/{Title} ({Year})/metadata.json
    {path}/series/{Title} ({Year})/... (same shape as movies)
    {path}/music/{Artist}/{Album} ({Year})/albumart.jpg
    {path}/music/{Artist}/{Album} ({Year})/fanart.jpg
    {path}/music/{Artist}/{Album} ({Year})/{Track Title}.lrc
    {path}/music/{Artist}/{Album} ({Year})/metadata.json

When year is unknown, the "(Year)" suffix is simply omitted from the
directory name until a later fetch resolves it (see _relocate_to_year_dir).

metadata.json tracks explicit ISO-8601 `last_checked`/`last_updated`
timestamps per artwork/lyrics entry, rather than relying on file mtime like
ImageCache/TextCache do - the point of this store is auditable, inspectable
staleness state, and a file copy/backup bumping mtime shouldn't count as
"we just checked".
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from mediainfo.config import MediaDataConfig

# What a `_fetch_*` stub (or, later, a real implementation) returns:
# (content_bytes, source_name) on success, or None if there's nothing new
# (not found, unreachable, etc.) - the caller must not treat None as an
# error, just "no update available right now".
FetchResult = Optional[Tuple[bytes, str]]

logger = logging.getLogger(__name__)

_METADATA_FILENAME = "metadata.json"

# Characters unsafe (or awkward) in a filename across common filesystems -
# replaced with "-". Deliberately conservative (covers Windows-reserved
# characters too) even though this runs on Linux, since the resulting
# folder names are meant to be portable/human-browsable.
_UNSAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize(name: str) -> str:
    """Make `name` safe to use as a single filesystem path segment,
    preserving spaces/parens/accents (only replaces genuinely unsafe
    characters, e.g. "AC/DC" -> "AC-DC")."""
    cleaned = _UNSAFE_CHARS_RE.sub("-", name).strip()
    return cleaned or "-"


class MediaDataStore:
    def __init__(self, config: MediaDataConfig):
        self.config = config
        self.root = Path(config.path).resolve()
        # Guards read-modify-write of a single item's metadata.json - cheap
        # insurance against a lost update if this store is ever called
        # concurrently (matches the pattern already used by
        # mediainfo.artwork_overrides.ArtworkOverrideStore).
        self._lock = threading.Lock()

    # -- path builders -----------------------------------------------------

    @staticmethod
    def _with_year(title: str, year: Optional[int]) -> str:
        base = _sanitize(title)
        return f"{base} ({year})" if year is not None else base

    def movie_dir(self, title: str, year: Optional[int]) -> Path:
        return self.root / "movies" / self._with_year(title, year)

    def series_dir(self, title: str, year: Optional[int]) -> Path:
        return self.root / "series" / self._with_year(title, year)

    def album_dir(self, artist: str, album: str, year: Optional[int]) -> Path:
        return self.root / "music" / _sanitize(artist) / self._with_year(album, year)

    # -- metadata.json I/O ---------------------------------------------------

    def _read_metadata(self, item_dir: Path) -> Dict[str, Any]:
        path = item_dir / _METADATA_FILENAME
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Corrupt %s at %s - ignoring", _METADATA_FILENAME, path)
            return {}

    def _write_metadata(self, item_dir: Path, data: Dict[str, Any]) -> None:
        """Write metadata.json atomically: a reader (including this same
        method running concurrently in another process) never observes a
        partially-written file, since the final `replace()` is a single
        filesystem operation rather than an in-place write."""
        item_dir.mkdir(parents=True, exist_ok=True)
        path = item_dir / _METADATA_FILENAME
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    @staticmethod
    def _atomic_write_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_bytes(content)
        tmp_path.replace(path)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _is_stale(entry: Dict[str, Any], max_age_days: Optional[int]) -> bool:
        """True if `entry` (an artwork/lyrics metadata.json entry) is older
        than `max_age_days` - or if it has no parseable `last_checked` at
        all, which is treated as "definitely needs a check". max_age_days
        of None means "never stale by age" (used for lyrics - see
        get_track_lyrics)."""
        if max_age_days is None:
            return False
        last_checked = entry.get("last_checked")
        if not last_checked:
            return True
        try:
            checked_at = datetime.fromisoformat(last_checked)
        except ValueError:
            return True
        return datetime.now(timezone.utc) - checked_at > timedelta(days=max_age_days)

    # -- cache-first + refresh-policy core -----------------------------------

    def _resolve_artwork(
        self,
        item_dir: Path,
        filename: str,
        metadata_key: str,
        max_age_days: Optional[int],
        fetch_fn: Callable[[], FetchResult],
    ) -> Optional[Path]:
        """Shared cache-first/refresh algorithm for one piece of content
        (an artwork file, or - via get_track_lyrics - a lyrics file) living
        at `item_dir / filename`, tracked under metadata.json's
        `artwork[metadata_key]` (or `lyrics` - see get_track_lyrics).

        - Missing entirely: always calls fetch_fn(); returns the new path
          on success, None if fetch_fn found nothing.
        - Present and not stale (or config.refresh.enabled is False):
          returns the local path immediately, without calling fetch_fn().
        - Present but stale: calls fetch_fn() synchronously (see the
          TODO below), always returns the *existing* local path right
          away regardless of the fetch's outcome - a slow/failed refresh
          never blocks or breaks the current call, it only affects what
          the *next* call sees.
        """
        path = item_dir / filename
        with self._lock:
            metadata = self._read_metadata(item_dir)
            artwork = metadata.setdefault("artwork", {})
            entry = artwork.get(metadata_key)

            if path.exists():
                if not self.config.refresh.enabled:
                    return path
                if not self._is_stale(entry or {}, max_age_days):
                    return path

                # TODO(async-refresh): this blocks the caller until fetch_fn
                # returns. A future version should hand this off to a
                # background task (or defer it to the next enrichment
                # pass) instead - see the plan this was built from.
                result = fetch_fn()
                now = self._now_iso()
                if entry is None:
                    entry = {"path": filename, "source": "", "last_checked": now, "last_updated": now}
                entry["last_checked"] = now
                if result is not None:
                    content, source = result
                    self._atomic_write_bytes(path, content)
                    entry["source"] = source
                    entry["last_updated"] = now
                artwork[metadata_key] = entry
                self._write_metadata(item_dir, metadata)
                return path

            # Missing entirely - always attempt a fetch, regardless of
            # config.refresh.enabled (that flag only gates re-checking
            # something we already have, not the first fetch).
            result = fetch_fn()
            if result is None:
                return None
            content, source = result
            self._atomic_write_bytes(path, content)
            now = self._now_iso()
            artwork[metadata_key] = {
                "path": filename, "source": source, "last_checked": now, "last_updated": now,
            }
            self._write_metadata(item_dir, metadata)
            return path
