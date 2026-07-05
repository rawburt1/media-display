"""Disk cache for text-based enrichment results (lyrics, AI-generated
descriptions) - keyed by an arbitrary string (typically a song's identity,
e.g. "artist - title"), not a URL like ImageCache. Foundation for roadmap
items 8/9; no current caller yet.

Each entry is a small JSON file under cache_dir/<namespace>/<hash>.json,
one namespace per plugin (e.g. "lrclib", "ollama_text") so different
enrichers' results never collide on the same cache key and can be
inspected/purged independently.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)


class TextCache:
    def __init__(self, cache_dir: Union[str, Path], max_age_days: int = 30):
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_seconds = max_age_days * 86400

    def _path_for(self, namespace: str, key: str) -> Path:
        namespace_dir = self.cache_dir / namespace
        namespace_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return namespace_dir / f"{digest}.json"

    def get(self, namespace: str, key: str) -> Optional[Any]:
        """Return the cached JSON-decoded value for (namespace, key), or
        None if there's no entry, it's past max_age_days, or it's
        corrupt."""
        path = self._path_for(namespace, key)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self.max_age_seconds:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Corrupt text cache entry %s - ignoring", path)
            return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        path = self._path_for(namespace, key)
        path.write_text(json.dumps(value), encoding="utf-8")

    def purge_expired(self) -> None:
        cutoff = time.time() - self.max_age_seconds
        for namespace_dir in self.cache_dir.iterdir():
            if not namespace_dir.is_dir():
                continue
            for path in namespace_dir.iterdir():
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    logger.info("Purged expired text cache entry %s", path.name)
