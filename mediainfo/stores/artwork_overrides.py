"""Manual artwork overrides: lets a user pin a specific image for a given
title/subtitle (e.g. a movie or show that never gets a good poster from
any enricher) via the config UI - the Orchestrator checks this store after
enrichment and, on a match, replaces the item's images with just the
pinned one (see Orchestrator._handle_new_item).

Stored as plain files on disk under `dir`, indexed by a small JSON file
(overrides.json) mapping a normalized "title|subtitle" key to the stored
image's filename - this is expected to hold a handful of manual entries at
most, so a database would be needless overhead.

Overrides are served via file:// URLs, which ImageCache.get_path() already
returns directly without downloading or running them through the minimum-
size filter (see cache.py) - appropriate here since the user deliberately
chose this exact image.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from mediainfo.models import Artwork

logger = logging.getLogger(__name__)

_INDEX_FILENAME = "overrides.json"


def _key(title: str, subtitle: str) -> str:
    return f"{title.strip().casefold()}|{subtitle.strip().casefold()}"


class ArtworkOverrideStore:
    def __init__(self, directory: str):
        # Resolve to an absolute path: Flask's send_file() resolves relative
        # paths against the app module's directory, not the cwd, so a
        # relative dir would point at the wrong location when serving
        # override images back (see config_ui.py's overrides_image route).
        self.dir = Path(directory).resolve()
        self.dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.dir / _INDEX_FILENAME
        self._lock = threading.Lock()
        self._index: Dict[str, dict] = self._load_index()

    def _load_index(self) -> Dict[str, dict]:
        if not self._index_path.exists():
            return {}
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read artwork override index at %s", self._index_path)
            return {}

    def _save_index(self) -> None:
        self._index_path.write_text(json.dumps(self._index, indent=2), encoding="utf-8")

    def list(self) -> List[dict]:
        """Return [{"title", "subtitle", "filename"}, ...] for every
        stored override, for the config UI's management page."""
        with self._lock:
            return [dict(entry) for entry in self._index.values()]

    def get(self, title: str, subtitle: str) -> Optional[Artwork]:
        with self._lock:
            entry = self._index.get(_key(title, subtitle))
        if entry is None:
            return None
        path = self.dir / entry["filename"]
        if not path.exists():
            return None
        return Artwork(url=f"file://{path.resolve()}", label="Manual override")

    def set(self, title: str, subtitle: str, content: bytes, extension: str = ".jpg") -> None:
        """Store `content` as the override image for (title, subtitle),
        replacing (and deleting the file for) any previous override for
        the same key.
        """
        key = _key(title, subtitle)
        filename = f"{uuid.uuid4().hex}{extension}"
        path = self.dir / filename
        path.write_bytes(content)

        with self._lock:
            old = self._index.get(key)
            self._index[key] = {"title": title, "subtitle": subtitle, "filename": filename}
            self._save_index()

        if old is not None and old["filename"] != filename:
            self._unlink(self.dir / old["filename"])

    def remove(self, title: str, subtitle: str) -> bool:
        """Remove the override for (title, subtitle), if any. Returns
        whether one existed."""
        with self._lock:
            entry = self._index.pop(_key(title, subtitle), None)
            if entry is None:
                return False
            self._save_index()
        self._unlink(self.dir / entry["filename"])
        return True

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            logger.exception("Failed to remove artwork override file %s", path)
