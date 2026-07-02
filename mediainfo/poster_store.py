"""Poster store: serves pre-placed image files for specific titles
(and optionally sources/channels) as artwork, before enrichers fill in
the rotation pool.

Each entry in the config maps a (title, optional source) pair to a
filename in the configured posters directory.  Matching is
case-insensitive on title; if no source is specified in an entry it
matches any source.  When a match is found the stored poster replaces
whatever artwork enrichers may have found - use artwork overrides
(see artwork_overrides.py) to pin artwork per specific episode rather
than per show.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)


def _norm(s: str) -> str:
    return s.strip().casefold()


class PosterStore:
    def __init__(self, directory: str, entries: List[dict]):
        self._dir = Path(directory).resolve()
        self._entries = [
            {
                "title": _norm(e.get("title", "")),
                "source": _norm(e["source"]) if e.get("source") else None,
                "file": e.get("file", ""),
            }
            for e in entries
        ]

    def get(self, now_playing: NowPlaying) -> Optional[Artwork]:
        title = _norm(now_playing.title)
        source = _norm(now_playing.source)
        for entry in self._entries:
            if entry["title"] != title:
                continue
            if entry["source"] is not None and entry["source"] != source:
                continue
            path = self._dir / entry["file"]
            if not path.exists():
                logger.warning(
                    "Poster file not found for %r: %s", now_playing.title, path
                )
                return None
            return Artwork(url=f"file://{path}", label="Poster")
        return None
