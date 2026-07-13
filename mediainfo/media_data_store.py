"""Unified on-disk media metadata/artwork/lyrics cache: one human-browsable
folder per movie/series/album (e.g. `movies/Alien (1979)/poster.jpg`), each
with a `metadata.json` tracking where each piece of content came from and
when it was last checked/updated.

Wired into the live enrichment pipeline via mediainfo/enrichers/
mediadata.py (artwork + lyrics word cloud) and mediadata_lyrics.py (music
lyrics) - opt-in, off by default. Additive: ImageCache, TextCache,
PosterStore, and ArtworkOverrideStore are all untouched and keep working
exactly as before.

Public API (see MediaDataStore's methods for details):
    get_movie_poster(title, year) / get_movie_fanart(title, year)
    get_series_poster(title, year) / get_series_fanart(title, year)
    get_album_art(artist, album, year) / get_album_fanart(artist, album, year)
    get_artist_photo(artist)
    get_track_lyrics(artist, album, title, year=None)
    get_track_wordcloud(artist, album, title, year=None)
    refresh_movie(title, year) / refresh_series(title, year)
    refresh_album(artist, album, year) / refresh_artist_photo(artist)
    refresh_track_lyrics(artist, album, title, year=None)
    refresh_track_wordcloud(artist, album, title, year=None)

Each `get_*` is cache-first, following the per-media-type refresh policy
in MediaDataConfig.refresh; each `refresh_*` forces an immediate
fetch/regeneration attempt regardless of freshness and returns whether
anything was actually updated.

For the full rationale - provider fallback order, the on-disk directory
layout, and why freshness uses explicit timestamps instead of file mtime -
see docs/adr/0002-media-data-store-layout.md.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import shutil
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from mediainfo.cache import ImageCache
from mediainfo.config import MediaDataConfig
from mediainfo.disk_eviction import EvictionUnit
from mediainfo.disk_eviction import evict_by_size as _evict_by_size
from mediainfo.enrichers import discogs, fanarttv, lastfm, lrclib, musicbrainz, tmdb, wikipedia
from mediainfo.models import Artwork

# What a `_fetch_*` stub (or, later, a real implementation) returns:
# (content_bytes, source_name) on success, or None if there's nothing new
# (not found, unreachable, etc.) - the caller must not treat None as an
# error, just "no update available right now".
FetchResult = Optional[Tuple[bytes, str]]

logger = logging.getLogger(__name__)

_METADATA_FILENAME = "metadata.json"

# How long a resolved TMDb/fanart.tv lookup is memoized for - just long
# enough to cover get_movie_poster()+get_movie_fanart() (or the series
# equivalent, or refresh_movie()/refresh_series()) being called back-to-
# back for the same title, which would otherwise repeat the exact same
# search/lookup twice. Deliberately far shorter than the days-scale
# refresh.movies_days/series_days policy that governs when a *new* fetch
# happens at all - this must not paper over that by serving a stale
# in-memory result long after it should have re-checked.
_LOOKUP_CACHE_SECONDS = 30

# Characters unsafe (or awkward) in a filename across common filesystems -
# replaced with "-". Deliberately conservative (covers Windows-reserved
# characters too) even though this runs on Linux, since the resulting
# folder names are meant to be portable/human-browsable.
_UNSAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# How often maybe_evict_by_size() actually walks the store's directory
# tree - called opportunistically from the mediadata enrichers' enrich()
# (once per track change), so this keeps it from re-walking a
# possibly-large tree on every single track change.
_EVICTION_CHECK_INTERVAL_SECONDS = 24 * 60 * 60


def _sanitize(name: str) -> str:
    """Make `name` safe to use as a single filesystem path segment,
    preserving spaces/parens/accents (only replaces genuinely unsafe
    characters, e.g. "AC/DC" -> "AC-DC")."""
    cleaned = _UNSAFE_CHARS_RE.sub("-", name).strip()
    return cleaned or "-"


class MediaDataStore:
    def __init__(
        self,
        config: MediaDataConfig,
        cache: Optional[ImageCache] = None,
        discogs_token: str = "",
        tmdb_api_key: str = "",
        fanarttv_api_key: str = "",
        lastfm_api_key: str = "",
    ):
        self.config = config
        self.root = Path(config.path).resolve()
        # Guards read-modify-write of a single item's metadata.json - cheap
        # insurance against a lost update if this store is ever called
        # concurrently (matches the pattern already used by
        # mediainfo.artwork_overrides.ArtworkOverrideStore).
        self._lock = threading.Lock()
        # Used by _download_bytes() to actually fetch resolved artwork URLs
        # (reusing ImageCache's existing minimum-size filtering, JPEG
        # normalization, and User-Agent handling rather than duplicating
        # that logic here) - optional so existing tests that only exercise
        # the cache/refresh-policy engine don't need to construct one.
        # Without it, every real fetch simply finds nothing (same
        # externally-visible behaviour as the old always-None stubs).
        self._cache = cache
        # Discogs personal access token, for the album-art fallback when
        # MusicBrainz/Cover Art Archive has nothing - blank means "skip
        # Discogs", not an error (matches how DiscogsEnricher itself
        # behaves without a token).
        self._discogs_token = discogs_token
        # TMDb credential (v3 key or v4 token, see tmdb.py), used for both
        # movie and series poster/fanart search - blank means "skip
        # movie/series artwork entirely" (same "no error, just nothing to
        # do" behavior as a blank discogs_token).
        self._tmdb_api_key = tmdb_api_key
        # fanart.tv personal API key, for a movie-poster/fanart fallback
        # when TMDb has nothing (using the TMDb id already resolved) -
        # blank means "skip fanart.tv". Not used for series - see
        # _fetch_series_artwork's docstring for why.
        self._fanarttv_api_key = fanarttv_api_key
        # Last.fm API key, for the artist-photo fallback when Wikipedia has
        # nothing - blank means "skip Last.fm" (same "no error, just
        # nothing to do" behavior as a blank discogs_token).
        self._lastfm_api_key = lastfm_api_key
        # Short-lived memoization for _cached_lookup() - see
        # _LOOKUP_CACHE_SECONDS.
        self._lookup_cache: Dict[tuple, Tuple[float, Any]] = {}
        # Artwork/lyrics file Paths with a background refresh currently in
        # flight (see _resolve_content's stale-but-present branch) - guards
        # against starting a second background fetch for the same file
        # while one is already running.
        self._refresh_in_progress: set = set()
        # self-gates maybe_evict_by_size() - see _EVICTION_CHECK_INTERVAL_SECONDS.
        self._last_eviction_check: Optional[float] = None
        self.max_disk_bytes = config.max_disk_mb * 1024 * 1024 if config.max_disk_mb else None

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

    def _resolve_content(
        self,
        item_dir: Path,
        filename: str,
        get_entry: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
        set_entry: Callable[[Dict[str, Any], Dict[str, Any]], None],
        max_age_days: Optional[int],
        fetch_fn: Callable[[], FetchResult],
        force: bool = False,
    ) -> Optional[Path]:
        """Shared cache-first/refresh algorithm for one piece of content
        living at `item_dir / filename`. `get_entry`/`set_entry` locate
        that content's tracking entry within the metadata dict - a flat
        `artwork[key]` for artwork (see _resolve_artwork), or a nested
        `tracks[title]["lyrics"]` for lyrics (see _resolve_track_lyrics) -
        so this method itself doesn't need to know which shape it's
        working with.

        - Missing entirely: always calls fetch_fn(); returns the new path
          on success, None if fetch_fn found nothing.
        - Present and not stale (or config.refresh.enabled is False):
          returns the local path immediately, without calling fetch_fn().
        - Present but stale (and not forced): fetch_fn() runs on a
          background thread (see _background_refresh) - always returns
          the *existing* local path right away regardless of the fetch's
          outcome, a slow/failed refresh never blocks or breaks the
          current call, it only affects what a *later* call sees once the
          background fetch finishes.
        - `force=True` (the manual refresh_*() API - forces an attempt
          regardless of freshness/config.refresh.enabled): calls
          fetch_fn() synchronously, since that API's caller
          (_was_updated_by) wants to know whether the fetch found
          something new right now, not eventually in the background.
        """
        path = item_dir / filename
        with self._lock:
            metadata = self._read_metadata(item_dir)
            entry = get_entry(metadata)

            if path.exists():
                if not force:
                    # Bump mtime on every serve, not just a fresh fetch -
                    # evict_by_size()'s LRU eviction needs a real
                    # last-used signal (M2 in
                    # docs/architecture-usability-review-2026-07.md).
                    path.touch()
                    if not self.config.refresh.enabled:
                        return path
                    if not self._is_stale(entry or {}, max_age_days):
                        return path

                    # Stale and not forced: serve the existing file
                    # immediately, refreshing in the background so a
                    # slow/hung source lookup never blocks the caller.
                    # Skip starting a second refresh if one for this
                    # exact file is already in flight.
                    if path not in self._refresh_in_progress:
                        self._refresh_in_progress.add(path)
                        threading.Thread(
                            target=self._background_refresh,
                            args=(item_dir, filename, path, get_entry, set_entry, fetch_fn),
                            daemon=True,
                            name=f"mediadata-refresh-{filename}",
                        ).start()
                    return path

                # force=True: synchronous - see docstring above.
                result = fetch_fn()
                now = self._now_iso()
                if entry is None:
                    entry = {
                        "path": filename,
                        "source": "",
                        "last_checked": now,
                        "last_updated": now,
                    }
                entry["last_checked"] = now
                if result is not None:
                    content, source = result
                    self._atomic_write_bytes(path, content)
                    entry["source"] = source
                    entry["last_updated"] = now
                set_entry(metadata, entry)
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
            entry = {"path": filename, "source": source, "last_checked": now, "last_updated": now}
            set_entry(metadata, entry)
            self._write_metadata(item_dir, metadata)
            return path

    def _background_refresh(
        self,
        item_dir: Path,
        filename: str,
        path: Path,
        get_entry: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
        set_entry: Callable[[Dict[str, Any], Dict[str, Any]], None],
        fetch_fn: Callable[[], FetchResult],
    ) -> None:
        """Runs fetch_fn() off the caller's thread for _resolve_content's
        stale-but-present branch, then applies the same metadata/bytes
        update the synchronous force=True path applies inline. The
        try/except here is a safety net for running unsupervised on a
        bare daemon thread - every real _fetch_* implementation already
        catches its own errors and returns None, but this must never let
        an unexpected exception go unlogged."""
        try:
            result = fetch_fn()
        except Exception:
            logger.exception("MediaDataStore: background refresh failed for %s", path)
            result = None

        with self._lock:
            metadata = self._read_metadata(item_dir)
            entry = get_entry(metadata)
            now = self._now_iso()
            if entry is None:
                entry = {"path": filename, "source": "", "last_checked": now, "last_updated": now}
            entry["last_checked"] = now
            if result is not None:
                content, source = result
                self._atomic_write_bytes(path, content)
                entry["source"] = source
                entry["last_updated"] = now
            set_entry(metadata, entry)
            self._write_metadata(item_dir, metadata)
            self._refresh_in_progress.discard(path)

    def _resolve_artwork(
        self,
        item_dir: Path,
        filename: str,
        metadata_key: str,
        max_age_days: Optional[int],
        fetch_fn: Callable[[], FetchResult],
        force: bool = False,
    ) -> Optional[Path]:
        """_resolve_content() for a flat metadata.json artwork[metadata_key]
        entry - see _resolve_content's docstring for the actual algorithm."""

        def get_entry(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            return metadata.get("artwork", {}).get(metadata_key)

        def set_entry(metadata: Dict[str, Any], entry: Dict[str, Any]) -> None:
            metadata.setdefault("artwork", {})[metadata_key] = entry

        return self._resolve_content(
            item_dir,
            filename,
            get_entry,
            set_entry,
            max_age_days,
            fetch_fn,
            force,
        )

    def _resolve_track_lyrics(
        self,
        item_dir: Path,
        filename: str,
        title: str,
        fetch_fn: Callable[[], FetchResult],
        force: bool = False,
    ) -> Optional[Path]:
        """_resolve_content() for a nested metadata.json
        tracks[title]["lyrics"] entry (nested, unlike artwork's flat
        dict, since one album has many tracks) - always max_age_days=None
        (lyrics are never auto-refreshed by age, see get_track_lyrics)."""

        def get_entry(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            return metadata.get("tracks", {}).get(title, {}).get("lyrics")

        def set_entry(metadata: Dict[str, Any], entry: Dict[str, Any]) -> None:
            metadata.setdefault("tracks", {}).setdefault(title, {})["lyrics"] = entry

        return self._resolve_content(
            item_dir,
            filename,
            get_entry,
            set_entry,
            None,
            fetch_fn,
            force,
        )

    def _resolve_track_wordcloud(
        self,
        item_dir: Path,
        filename: str,
        title: str,
        fetch_fn: Callable[[], FetchResult],
        force: bool = False,
    ) -> Optional[Path]:
        """_resolve_content() for a nested metadata.json
        tracks[title]["wordcloud"] entry - mirrors _resolve_track_lyrics,
        including max_age_days=None (a generated word cloud is never
        auto-refreshed by age; only a missing file or an explicit
        refresh_track_wordcloud() call ever regenerates it)."""

        def get_entry(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            return metadata.get("tracks", {}).get(title, {}).get("wordcloud")

        def set_entry(metadata: Dict[str, Any], entry: Dict[str, Any]) -> None:
            metadata.setdefault("tracks", {}).setdefault(title, {})["wordcloud"] = entry

        return self._resolve_content(
            item_dir,
            filename,
            get_entry,
            set_entry,
            None,
            fetch_fn,
            force,
        )

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

    def _cached_lookup(self, key: tuple, fetch_fn: Callable[[], Any]) -> Any:
        """Memoize an external search/lookup call (e.g. tmdb.find_movie,
        fanarttv.fetch) for _LOOKUP_CACHE_SECONDS, so resolving poster and
        fanart for the same title back-to-back (get_movie_poster() then
        get_movie_fanart(), or refresh_movie()'s loop over both) doesn't
        repeat the identical network call. `key` must include a tag for
        which lookup this is, since different lookups may share arguments
        (e.g. a title also being searched via find_tv)."""
        now = time.monotonic()
        cached = self._lookup_cache.get(key)
        if cached is not None and now - cached[0] < _LOOKUP_CACHE_SECONDS:
            return cached[1]
        value = fetch_fn()
        self._lookup_cache[key] = (now, value)
        return value

    # -- movies ---------------------------------------------------------

    def get_movie_poster(self, title: str, year: Optional[int]) -> Optional[Path]:
        item_dir = self.movie_dir(title, year)
        return self._resolve_artwork(
            item_dir,
            "poster.jpg",
            "poster",
            self.config.refresh.movies_days,
            lambda: self._fetch_movie_artwork(title, year, "poster"),
        )

    def get_movie_fanart(self, title: str, year: Optional[int]) -> Optional[Path]:
        item_dir = self.movie_dir(title, year)
        return self._resolve_artwork(
            item_dir,
            "fanart.jpg",
            "fanart",
            self.config.refresh.movies_days,
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
                item_dir,
                key,
                lambda: self._resolve_artwork(
                    item_dir,
                    filename,
                    key,
                    self.config.refresh.movies_days,
                    lambda: self._fetch_movie_artwork(title, year, key),
                    force=True,
                ),
            )
            updated = updated or changed
        return updated

    def _fetch_movie_artwork(self, title: str, year: Optional[int], kind: str) -> FetchResult:
        """TMDb first (free, one credential covers movies+series), falling
        back to fanart.tv (if a key is configured) using the TMDb id just
        resolved - mirrors _fetch_album_artwork's "free source, then a
        keyed fallback" shape."""
        resolved = self._resolve_movie_artwork_url(title, year, kind)
        if resolved is None:
            return None
        url, source = resolved
        return self._download_bytes(url, source)

    def _resolve_movie_artwork_url(
        self, title: str, year: Optional[int], kind: str
    ) -> Optional[Tuple[str, str]]:
        movie = self._find_tmdb_movie(title, year) if self._tmdb_api_key else None
        url = tmdb.artwork_url(movie, kind)
        if url:
            return url, "tmdb"

        tmdb_id = movie.get("id") if movie else None
        if self._fanarttv_api_key and tmdb_id:
            data = self._fetch_fanarttv_movie(tmdb_id, title)
            if data:
                field = "movieposter" if kind == "poster" else "moviebackground"
                url = fanarttv.best_url(data.get(field))
                if url:
                    return url, "fanarttv"

        return None

    def _find_tmdb_movie(self, title: str, year: Optional[int]) -> Optional[dict]:
        def fetch() -> Optional[dict]:
            try:
                return tmdb.find_movie(self._tmdb_api_key, title, year)
            except Exception:
                logger.exception("MediaDataStore: TMDb movie search failed for %r", title)
                return None

        return self._cached_lookup(("tmdb_movie", title, year), fetch)

    def _fetch_fanarttv_movie(self, tmdb_id: str, title: str) -> Optional[dict]:
        def fetch() -> Optional[dict]:
            try:
                return fanarttv.fetch(self._fanarttv_api_key, f"movies/{tmdb_id}")
            except Exception:
                logger.exception("MediaDataStore: fanart.tv movie lookup failed for %r", title)
                return None

        return self._cached_lookup(("fanarttv_movie", tmdb_id), fetch)

    # -- series (mirrors movies) ------------------------------------------

    def get_series_poster(self, title: str, year: Optional[int]) -> Optional[Path]:
        item_dir = self.series_dir(title, year)
        return self._resolve_artwork(
            item_dir,
            "poster.jpg",
            "poster",
            self.config.refresh.series_days,
            lambda: self._fetch_series_artwork(title, year, "poster"),
        )

    def get_series_fanart(self, title: str, year: Optional[int]) -> Optional[Path]:
        item_dir = self.series_dir(title, year)
        return self._resolve_artwork(
            item_dir,
            "fanart.jpg",
            "fanart",
            self.config.refresh.series_days,
            lambda: self._fetch_series_artwork(title, year, "fanart"),
        )

    def refresh_series(self, title: str, year: Optional[int]) -> bool:
        """Force a refresh attempt for both poster and fanart, regardless
        of freshness. Returns True if at least one was actually updated."""
        item_dir = self.series_dir(title, year)
        updated = False
        for filename, key in (("poster.jpg", "poster"), ("fanart.jpg", "fanart")):
            changed = self._was_updated_by(
                item_dir,
                key,
                lambda: self._resolve_artwork(
                    item_dir,
                    filename,
                    key,
                    self.config.refresh.series_days,
                    lambda: self._fetch_series_artwork(title, year, key),
                    force=True,
                ),
            )
            updated = updated or changed
        return updated

    def _fetch_series_artwork(self, title: str, year: Optional[int], kind: str) -> FetchResult:
        """TMDb only - no fanart.tv fallback here, since fanart.tv's TV
        lookup needs a TVDB id specifically and this store has no way to
        resolve one without a separate thetvdb.com login flow (see the
        module docstring for why that integration was skipped)."""
        resolved = self._resolve_series_artwork_url(title, year, kind)
        if resolved is None:
            return None
        url, source = resolved
        return self._download_bytes(url, source)

    def _resolve_series_artwork_url(
        self, title: str, year: Optional[int], kind: str
    ) -> Optional[Tuple[str, str]]:
        if not self._tmdb_api_key:
            return None
        show = self._find_tmdb_tv(title)
        url = tmdb.artwork_url(show, kind)
        return (url, "tmdb") if url else None

    def _find_tmdb_tv(self, title: str) -> Optional[dict]:
        def fetch() -> Optional[dict]:
            try:
                return tmdb.find_tv(self._tmdb_api_key, title)
            except Exception:
                logger.exception("MediaDataStore: TMDb TV search failed for %r", title)
                return None

        return self._cached_lookup(("tmdb_tv", title), fetch)

    # -- music ------------------------------------------------------------

    def get_album_art(self, artist: str, album: str, year: Optional[int]) -> Optional[Path]:
        item_dir = self.album_dir(artist, album, year)
        return self._resolve_artwork(
            item_dir,
            "albumart.jpg",
            "albumart",
            self.config.refresh.music_days,
            lambda: self._fetch_album_artwork(artist, album, year, "albumart"),
        )

    def get_album_fanart(self, artist: str, album: str, year: Optional[int]) -> Optional[Path]:
        item_dir = self.album_dir(artist, album, year)
        return self._resolve_artwork(
            item_dir,
            "fanart.jpg",
            "fanart",
            self.config.refresh.music_days,
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
                item_dir,
                key,
                lambda: self._resolve_artwork(
                    item_dir,
                    filename,
                    key,
                    self.config.refresh.music_days,
                    lambda: self._fetch_album_artwork(artist, album, year, key),
                    force=True,
                ),
            )
            updated = updated or changed
        return updated

    def artist_dir(self, artist: str) -> Path:
        """The artist's own directory (parent of its per-album
        subdirectories) - where artist.jpg and its metadata.json live,
        separate from any one album's metadata."""
        return self.root / "music" / _sanitize(artist)

    def get_artist_photo(self, artist: str) -> Optional[Path]:
        """Wikipedia-first, Last.fm-fallback artist photo - reuses the
        music_days refresh policy (an artist's photo changes about as
        rarely as an album's cover art)."""
        item_dir = self.artist_dir(artist)
        return self._resolve_artwork(
            item_dir,
            "artist.jpg",
            "artist_photo",
            self.config.refresh.music_days,
            lambda: self._fetch_artist_photo(artist),
        )

    def refresh_artist_photo(self, artist: str) -> bool:
        item_dir = self.artist_dir(artist)
        return self._was_updated_by(
            item_dir,
            "artist_photo",
            lambda: self._resolve_artwork(
                item_dir,
                "artist.jpg",
                "artist_photo",
                self.config.refresh.music_days,
                lambda: self._fetch_artist_photo(artist),
                force=True,
            ),
        )

    def _fetch_artist_photo(self, artist: str) -> FetchResult:
        """Real implementation: Wikipedia first (free, no key), falling
        back to Last.fm if an API key is configured and Wikipedia has
        nothing - mirrors _fetch_album_artwork's "free source, then a
        configured-key fallback" shape."""
        resolved = self._resolve_artist_photo_url(artist)
        if resolved is None:
            return None
        url, source = resolved
        return self._download_bytes(url, source)

    def _resolve_artist_photo_url(self, artist: str) -> Optional[Tuple[str, str]]:
        try:
            result = wikipedia.lookup(wikipedia.music_artist_queries(artist))
            if result is not None:
                _, thumbnail = result
                if thumbnail:
                    return thumbnail, "wikipedia"
        except Exception:
            logger.exception("MediaDataStore: Wikipedia lookup failed for artist %r", artist)

        if not self._lastfm_api_key:
            return None
        try:
            url = lastfm.fetch_artist_image(artist, self._lastfm_api_key)
        except Exception:
            logger.exception("MediaDataStore: Last.fm lookup failed for artist %r", artist)
            return None
        return (url, "lastfm") if url else None

    def _fetch_album_artwork(
        self, artist: str, album: str, year: Optional[int], kind: str
    ) -> FetchResult:
        """Real implementation for kind == "albumart": MusicBrainz/Cover
        Art Archive first (free, no key), falling back to Discogs if a
        token is configured and MusicBrainz has nothing.

        kind == "fanart" is deliberately left unfetched: neither source
        has a distinct "background art" concept for an album (both only
        ever give a front cover) - returning that same cover under a
        "fanart" label would be misleading, so get_album_fanart() simply
        finds nothing until a real background-art source is added.
        """
        if kind != "albumart":
            return None
        resolved = self._resolve_album_cover_url(artist, album)
        if resolved is None:
            return None
        url, source = resolved
        return self._download_bytes(url, source)

    def _resolve_album_cover_url(self, artist: str, album: str) -> Optional[Tuple[str, str]]:
        try:
            resolved_ids = musicbrainz.resolve_release_group_ids(None, artist, album)
            if resolved_ids is not None:
                url = musicbrainz.fetch_front_cover(resolved_ids[1])
                if url:
                    return url, "musicbrainz"
        except Exception:
            logger.exception("MediaDataStore: MusicBrainz lookup failed for %r - %r", artist, album)

        if not self._discogs_token:
            return None
        try:
            url = discogs.find_cover(self._discogs_token, artist, album)
        except Exception:
            logger.exception("MediaDataStore: Discogs lookup failed for %r - %r", artist, album)
            return None
        return (url, "discogs") if url else None

    def _download_bytes(self, url: str, source: str) -> FetchResult:
        if self._cache is None:
            logger.warning("MediaDataStore: no ImageCache configured - cannot download %s", url)
            return None
        temp_path = self._cache.download_temp(Artwork(url=url))
        if temp_path is None:
            return None
        try:
            content = temp_path.read_bytes()
        except OSError:
            logger.exception("MediaDataStore: failed to read downloaded artwork from %s", temp_path)
            return None
        finally:
            temp_path.unlink(missing_ok=True)
        return content, source

    # -- lyrics -------------------------------------------------------------
    #
    # Unlike artwork, lyrics are never auto-refreshed by age - only a
    # missing file, or an explicit refresh_track_lyrics() call, ever
    # triggers a fetch (see _resolve_track_lyrics's max_age_days=None).
    # `year` is optional (unlike refresh_album's) to match the manual
    # refresh API the roadmap specified exactly
    # (store.refresh_track_lyrics(artist, album, title)); pass it too if
    # known, so lyrics land in the same year'd album directory as its
    # artwork rather than a separate no-year one.

    def get_track_lyrics(
        self, artist: str, album: str, title: str, year: Optional[int] = None
    ) -> Optional[str]:
        item_dir = self.album_dir(artist, album, year)
        filename = f"{_sanitize(title)}.lrc"
        path = self._resolve_track_lyrics(
            item_dir,
            filename,
            title,
            lambda: self._fetch_lyrics(artist, album, title),
        )
        return path.read_text(encoding="utf-8") if path is not None else None

    def refresh_track_lyrics(
        self, artist: str, album: str, title: str, year: Optional[int] = None
    ) -> bool:
        """Force a lyrics refetch attempt, regardless of whether lyrics
        are already cached. Returns True if lyrics were actually updated."""
        item_dir = self.album_dir(artist, album, year)
        filename = f"{_sanitize(title)}.lrc"

        def _entry() -> Optional[Dict[str, Any]]:
            return self._read_metadata(item_dir).get("tracks", {}).get(title, {}).get("lyrics")

        before = (_entry() or {}).get("last_updated")
        self._resolve_track_lyrics(
            item_dir,
            filename,
            title,
            lambda: self._fetch_lyrics(artist, album, title),
            force=True,
        )
        after = (_entry() or {}).get("last_updated")
        return after != before

    def _fetch_lyrics(self, artist: str, album: str, title: str) -> FetchResult:
        """Real implementation via LRCLIB (mediainfo/enrichers/lrclib.py's
        extracted fetch_search()). Always uses the fuzzy search endpoint,
        never the exact-match one - this store's API has no duration
        parameter to pass, unlike LrclibEnricher's own duration-aware
        preference for the exact-match endpoint when available.

        Prefers synced (LRC-timestamped) lyrics for the stored .lrc file,
        since that's the format its extension implies, falling back to
        plain lyrics (still better than nothing) when synced isn't
        available.
        """
        try:
            result = lrclib.fetch_search(artist, title)
        except Exception:
            logger.exception("MediaDataStore: LRCLIB lookup failed for %r - %r", artist, title)
            return None
        if result is None:
            return None
        lyrics = result.get("syncedLyrics") or result.get("plainLyrics") or ""
        if not lyrics:
            return None
        return lyrics.encode("utf-8"), "lrclib"

    # -- lyrics word cloud ----------------------------------------------------
    #
    # A derived asset, not an external fetch: both lyrics and album art must
    # already be resolvable (cache-first, so this itself triggers a fetch for
    # either if missing) before anything is rendered. Like lyrics, never
    # auto-refreshed by age - only a missing file or an explicit
    # refresh_track_wordcloud() call regenerates it. Non-masked only (see
    # mediainfo/lyrics_wordcloud.py - the masked mode doesn't reliably trace
    # a photographic album cover's shape, so it isn't wired in here).

    def get_track_wordcloud(
        self, artist: str, album: str, title: str, year: Optional[int] = None
    ) -> Optional[Path]:
        """Non-masked lyrics word-cloud PNG for one track, colored from its
        album art. Returns None if either lyrics or album art can't be
        found. Stored next to the track's .lrc file (see the module
        docstring's directory layout)."""
        lyrics = self.get_track_lyrics(artist, album, title, year)
        if not lyrics:
            return None
        album_art_path = self.get_album_art(artist, album, year)
        if album_art_path is None:
            return None

        item_dir = self.album_dir(artist, album, year)
        filename = f"{_sanitize(title)}.wordcloud_nomask.png"
        return self._resolve_track_wordcloud(
            item_dir,
            filename,
            title,
            lambda: self._render_wordcloud(lyrics, album_art_path),
        )

    def refresh_track_wordcloud(
        self, artist: str, album: str, title: str, year: Optional[int] = None
    ) -> bool:
        """Force a word-cloud regeneration attempt, regardless of whether
        one is already cached - e.g. after refresh_track_lyrics() or
        refresh_album() picked up new lyrics or new art. Returns True if
        the word cloud was actually (re)generated; False (a no-op) if
        lyrics or album art aren't resolvable."""
        lyrics = self.get_track_lyrics(artist, album, title, year)
        if not lyrics:
            return False
        album_art_path = self.get_album_art(artist, album, year)
        if album_art_path is None:
            return False

        item_dir = self.album_dir(artist, album, year)
        filename = f"{_sanitize(title)}.wordcloud_nomask.png"

        def _entry() -> Optional[Dict[str, Any]]:
            return self._read_metadata(item_dir).get("tracks", {}).get(title, {}).get("wordcloud")

        before = (_entry() or {}).get("last_updated")
        self._resolve_track_wordcloud(
            item_dir,
            filename,
            title,
            lambda: self._render_wordcloud(lyrics, album_art_path),
            force=True,
        )
        after = (_entry() or {}).get("last_updated")
        return after != before

    def _render_wordcloud(self, lyrics_text: str, album_art_path: Path) -> FetchResult:
        """Real implementation: renders a non-masked word cloud (see
        mediainfo/lyrics_wordcloud.py) to a temp file and reads it back as
        bytes, matching every other _fetch_*'s (content_bytes, source)
        contract even though nothing is actually downloaded over the
        network - lets this reuse _resolve_content's cache/atomic-write/
        metadata machinery unchanged. `wordcloud` (and the matplotlib it
        pulls in) is imported lazily here rather than at module level,
        since most installs never exercise this path (off by default -
        see MediaDataWordcloudConfig)."""
        from mediainfo.lyrics_wordcloud import generate as generate_wordcloud

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir) / "wordcloud.png"
                generate_wordcloud(lyrics_text, album_art_path, tmp_path, use_mask=False)
                content = tmp_path.read_bytes()
        except Exception:
            logger.exception("MediaDataStore: word-cloud generation failed")
            return None
        return content, "generated"

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

    # -- size-capped eviction (M2) --------------------------------------

    def maybe_evict_by_size(self) -> None:
        """evict_by_size(), at most once every
        _EVICTION_CHECK_INTERVAL_SECONDS - cheap self-gating so callers
        (the mediadata enrichers' enrich(), invoked on every track change)
        can call this unconditionally without re-walking the whole store's
        directory tree on every single track change.

        Never raises - a permissions error or similar deleting one item
        must not also break that tick's real artwork/lyrics lookup for
        the enricher calling this, matching this project's "one broken
        thing never breaks the rest of the pipeline" convention.
        """
        now = time.monotonic()
        if (
            self._last_eviction_check is not None
            and now - self._last_eviction_check < _EVICTION_CHECK_INTERVAL_SECONDS
        ):
            return
        self._last_eviction_check = now
        try:
            self.evict_by_size()
        except Exception:
            logger.exception("MediaDataStore: size-capped eviction failed")

    def evict_by_size(self) -> None:
        """Size-capped LRU eviction across the whole store (M2 in
        docs/architecture-usability-review-2026-07.md) - a backstop
        against unbounded growth, independent of the per-media-type
        refresh policy (which governs when content is re-checked, not
        whether old content is ever removed at all). No-op if
        config.max_disk_mb is 0 (uncapped).

        Eviction units are whole item directories, not individual files:
        movies/{Title} ({Year})/, series/{Title} ({Year})/, each
        music/{Artist}/{Album} ({Year})/, and music/{Artist}/'s own direct
        files (artist photo + metadata.json - excluding its Album
        subdirectories, which are their own separate units). Deleting a
        whole unit at once keeps metadata.json in sync with the artwork/
        lyrics files it describes; deleting individual files within a
        unit would leave stale metadata.json entries pointing at files
        that no longer exist. "Last used" per unit is the newest mtime
        among its files - _resolve_content() bumps a file's mtime on
        every serve, not just a fresh fetch, so this reflects actual use,
        not merely how recently something happened to be re-checked.
        """
        if self.max_disk_bytes is None:
            return
        units, delete_fns = self._eviction_units()
        deleted = _evict_by_size(units, self.max_disk_bytes, delete=lambda p: delete_fns[p]())
        for path in deleted:
            logger.info("Evicted least-recently-used mediadata item %s (size cap)", path)
        self._prune_empty_artist_dirs()

    def _eviction_units(self) -> Tuple[List[EvictionUnit], Dict[Path, Callable[[], None]]]:
        units: List[EvictionUnit] = []
        delete_fns: Dict[Path, Callable[[], None]] = {}

        for top in ("movies", "series"):
            top_dir = self.root / top
            if not top_dir.is_dir():
                continue
            for item_dir in top_dir.iterdir():
                if not item_dir.is_dir():
                    continue
                unit = self._unit_for_dir(item_dir, recursive=True)
                if unit is not None:
                    units.append(unit)
                    delete_fns[item_dir] = functools.partial(shutil.rmtree, item_dir)

        music_dir = self.root / "music"
        if music_dir.is_dir():
            for artist_dir in music_dir.iterdir():
                if not artist_dir.is_dir():
                    continue
                artist_unit = self._unit_for_dir(artist_dir, recursive=False)
                if artist_unit is not None:
                    units.append(artist_unit)
                    delete_fns[artist_dir] = functools.partial(
                        self._delete_direct_files, artist_dir
                    )
                for album_dir in artist_dir.iterdir():
                    if not album_dir.is_dir():
                        continue
                    album_unit = self._unit_for_dir(album_dir, recursive=True)
                    if album_unit is not None:
                        units.append(album_unit)
                        delete_fns[album_dir] = functools.partial(shutil.rmtree, album_dir)

        return units, delete_fns

    @staticmethod
    def _unit_for_dir(item_dir: Path, recursive: bool) -> Optional[EvictionUnit]:
        """One EvictionUnit covering every file directly in item_dir - or,
        if recursive, in its subdirectories too. recursive=False is only
        used for music/{Artist}/ itself, whose Album subdirectories are
        their own separate units (see _eviction_units) and must not be
        counted here. Returns None for a directory with no files of its
        own (nothing to evict as this unit - e.g. an artist dir that's
        just a container for Album subdirectories)."""
        files = item_dir.rglob("*") if recursive else item_dir.iterdir()
        total_size = 0
        last_used = 0.0
        for f in files:
            if not f.is_file():
                continue
            stat = f.stat()
            total_size += stat.st_size
            last_used = max(last_used, stat.st_mtime)
        if last_used == 0.0:
            return None
        return EvictionUnit(path=item_dir, last_used=last_used, size_bytes=total_size)

    @staticmethod
    def _delete_direct_files(dir_path: Path) -> None:
        for f in dir_path.iterdir():
            if f.is_file():
                f.unlink()

    def _prune_empty_artist_dirs(self) -> None:
        """Remove music/{Artist}/ directories left empty after eviction -
        e.g. once both its own artist-level files and every Album
        subdirectory have been evicted. Cosmetic only (an empty directory
        costs negligible disk space); never touches movies/series, whose
        item directories are already leaf units with nothing left to
        prune once evicted."""
        music_dir = self.root / "music"
        if not music_dir.is_dir():
            return
        for artist_dir in music_dir.iterdir():
            if artist_dir.is_dir() and not any(artist_dir.iterdir()):
                artist_dir.rmdir()
