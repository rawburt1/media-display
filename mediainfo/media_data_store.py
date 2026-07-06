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
        force: bool = False,
    ) -> Optional[Path]:
        """Shared cache-first/refresh algorithm for one piece of content
        (an artwork file, or - via get_track_lyrics - a lyrics file) living
        at `item_dir / filename`, tracked under metadata.json's
        `artwork[metadata_key]` (or `lyrics` - see get_track_lyrics).

        - Missing entirely: always calls fetch_fn(); returns the new path
          on success, None if fetch_fn found nothing.
        - Present and not stale (or config.refresh.enabled is False):
          returns the local path immediately, without calling fetch_fn().
        - Present but stale, OR `force=True` (the manual refresh_*() API -
          forces an attempt regardless of freshness/config.refresh.enabled):
          calls fetch_fn() synchronously (see the TODO below), always
          returns the *existing* local path right away regardless of the
          fetch's outcome - a slow/failed refresh never blocks or breaks
          the current call, it only affects what the *next* call sees.
        """
        path = item_dir / filename
        with self._lock:
            metadata = self._read_metadata(item_dir)
            artwork = metadata.setdefault("artwork", {})
            entry = artwork.get(metadata_key)

            if path.exists():
                if not force:
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

    def _was_updated_by(self, item_dir: Path, metadata_key: str, action: Callable[[], Any]) -> bool:
        """Run `action` (a _resolve_artwork(..., force=True) call) and
        report whether it actually changed metadata_key's last_updated -
        used by the public refresh_*() methods to return a plain bool
        without _resolve_artwork itself needing a different return type
        for its regular (non-force) callers."""
        before = (self._read_metadata(item_dir).get("artwork", {}).get(metadata_key) or {}).get(
            "last_updated"
        )
        action()
        after = (self._read_metadata(item_dir).get("artwork", {}).get(metadata_key) or {}).get(
            "last_updated"
        )
        return after != before

    # -- movies ---------------------------------------------------------

    def get_movie_poster(self, title: str, year: Optional[int]) -> Optional[Path]:
        item_dir = self.movie_dir(title, year)
        return self._resolve_artwork(
            item_dir, "poster.jpg", "poster", self.config.refresh.movies_days,
            lambda: self._fetch_movie_artwork(title, year, "poster"),
        )

    def get_movie_fanart(self, title: str, year: Optional[int]) -> Optional[Path]:
        item_dir = self.movie_dir(title, year)
        return self._resolve_artwork(
            item_dir, "fanart.jpg", "fanart", self.config.refresh.movies_days,
            lambda: self._fetch_movie_artwork(title, year, "fanart"),
        )

    def refresh_movie(self, title: str, year: Optional[int]) -> bool:
        """Force a refresh attempt for both poster and fanart, regardless
        of freshness - e.g. for a future config UI "Refresh poster"/
        "Refresh fanart" button. Returns True if at least one was
        actually updated."""
        item_dir = self.movie_dir(title, year)
        updated = False
        for filename, key in (("poster.jpg", "poster"), ("fanart.jpg", "fanart")):
            changed = self._was_updated_by(
                item_dir, key,
                lambda: self._resolve_artwork(
                    item_dir, filename, key, self.config.refresh.movies_days,
                    lambda: self._fetch_movie_artwork(title, year, key),
                    force=True,
                ),
            )
            updated = updated or changed
        return updated

    def _fetch_movie_artwork(self, title: str, year: Optional[int], kind: str) -> FetchResult:
        """STUB - always returns None (no update available). A real
        implementation would call an artwork API (e.g. TMDB/fanart.tv)
        here for `kind` ("poster" or "fanart") - deliberately not done in
        this pass, see the module docstring."""
        return None

    # -- series (mirrors movies) ------------------------------------------

    def get_series_poster(self, title: str, year: Optional[int]) -> Optional[Path]:
        item_dir = self.series_dir(title, year)
        return self._resolve_artwork(
            item_dir, "poster.jpg", "poster", self.config.refresh.series_days,
            lambda: self._fetch_series_artwork(title, year, "poster"),
        )

    def get_series_fanart(self, title: str, year: Optional[int]) -> Optional[Path]:
        item_dir = self.series_dir(title, year)
        return self._resolve_artwork(
            item_dir, "fanart.jpg", "fanart", self.config.refresh.series_days,
            lambda: self._fetch_series_artwork(title, year, "fanart"),
        )

    def refresh_series(self, title: str, year: Optional[int]) -> bool:
        """Force a refresh attempt for both poster and fanart, regardless
        of freshness. Returns True if at least one was actually updated."""
        item_dir = self.series_dir(title, year)
        updated = False
        for filename, key in (("poster.jpg", "poster"), ("fanart.jpg", "fanart")):
            changed = self._was_updated_by(
                item_dir, key,
                lambda: self._resolve_artwork(
                    item_dir, filename, key, self.config.refresh.series_days,
                    lambda: self._fetch_series_artwork(title, year, key),
                    force=True,
                ),
            )
            updated = updated or changed
        return updated

    def _fetch_series_artwork(self, title: str, year: Optional[int], kind: str) -> FetchResult:
        """STUB - always returns None. See _fetch_movie_artwork."""
        return None

    # -- music ------------------------------------------------------------

    def get_album_art(self, artist: str, album: str, year: Optional[int]) -> Optional[Path]:
        item_dir = self.album_dir(artist, album, year)
        return self._resolve_artwork(
            item_dir, "albumart.jpg", "albumart", self.config.refresh.music_days,
            lambda: self._fetch_album_artwork(artist, album, year, "albumart"),
        )

    def get_album_fanart(self, artist: str, album: str, year: Optional[int]) -> Optional[Path]:
        item_dir = self.album_dir(artist, album, year)
        return self._resolve_artwork(
            item_dir, "fanart.jpg", "fanart", self.config.refresh.music_days,
            lambda: self._fetch_album_artwork(artist, album, year, "fanart"),
        )

    def refresh_album(self, artist: str, album: str, year: Optional[int]) -> bool:
        """Force a refresh attempt for both album art and fanart,
        regardless of freshness. Returns True if at least one was
        actually updated."""
        item_dir = self.album_dir(artist, album, year)
        updated = False
        for filename, key in (("albumart.jpg", "albumart"), ("fanart.jpg", "fanart")):
            changed = self._was_updated_by(
                item_dir, key,
                lambda: self._resolve_artwork(
                    item_dir, filename, key, self.config.refresh.music_days,
                    lambda: self._fetch_album_artwork(artist, album, year, key),
                    force=True,
                ),
            )
            updated = updated or changed
        return updated

    def _fetch_album_artwork(
        self, artist: str, album: str, year: Optional[int], kind: str
    ) -> FetchResult:
        """STUB - always returns None. A real implementation would call
        MusicBrainz/fanart.tv/discogs here for `kind` ("albumart" or
        "fanart") - see the module docstring."""
        return None

    # -- year-discovered-later migration ----------------------------------

    def _relocate_to_year_dir(self, old_dir: Path, new_dir: Path) -> None:
        """Move an existing no-year directory's contents into the year'd
        directory once a fetch reveals the year - merges into an existing
        metadata.json at the destination (if any) rather than clobbering
        it, with the moved-in fields taking precedence. No-op if old_dir
        doesn't exist or old_dir == new_dir.
        """
        if old_dir == new_dir or not old_dir.exists():
            return
        with self._lock:
            old_metadata = self._read_metadata(old_dir)
            new_metadata = self._read_metadata(new_dir)
            new_dir.mkdir(parents=True, exist_ok=True)
            for item in old_dir.iterdir():
                if item.name == _METADATA_FILENAME:
                    # Merged into new_dir's metadata.json below instead of
                    # moved as-is - removed so old_dir ends up empty.
                    item.unlink()
                    continue
                item.replace(new_dir / item.name)
            merged = {**new_metadata, **old_metadata}
            self._write_metadata(new_dir, merged)
            old_dir.rmdir()
