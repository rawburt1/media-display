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
from pathlib import Path
from typing import Any, Dict, Optional

from mediainfo.config import MediaDataConfig

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
