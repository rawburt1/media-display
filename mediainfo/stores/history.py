"""Playback history: a persistent log of what has played.

Every genuinely new item the orchestrator routes to an output gets one
row here - a self-hosted scrobble log covering every source (Kodi, Sonos,
Spotify, vinyl, ...), not just music. Browsable at the web output's
/history page; the artwork shown there is resolved through the regular
image cache by the stored artwork URL, so no extra files are kept.

Deliberately small: a single SQLite table, newest-first reads, capped at
history.max_entries rows (oldest pruned on insert). A repeat of the most
recent entry within dedupe_window_seconds is skipped, so a source blip
that outlives the nothing-playing grace period (stop + resume of the same
item) doesn't log the same play twice.

One connection shared across threads (the orchestrator records; Flask
request threads read), guarded by a lock - same pattern as MusicLibrary.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Optional

from mediainfo.models import NowPlaying

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY,
    played_at REAL NOT NULL,
    source TEXT NOT NULL,
    media_type TEXT NOT NULL,
    title TEXT NOT NULL,
    subtitle TEXT NOT NULL DEFAULT '',
    album TEXT NOT NULL DEFAULT '',
    artwork_url TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_plays_played_at ON plays(played_at DESC);
"""


class PlaybackHistory:
    def __init__(
        self,
        db_path: str,
        max_entries: int = 1000,
        dedupe_window_seconds: int = 600,
    ):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.max_entries = max_entries
        self.dedupe_window_seconds = dedupe_window_seconds
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def record(self, now_playing: NowPlaying) -> None:
        """Log one play. Never raises - a history hiccup must not disturb
        the orchestrator tick that called it."""
        try:
            self._record(now_playing)
        except Exception:
            logger.exception("Failed to record playback history entry")

    def _record(self, now_playing: NowPlaying) -> None:
        now = time.time()
        # Prefer real cover/poster art for the row's thumbnail, not an
        # artist bio photo (see Artwork.is_artist_photo).
        artwork_url = next(
            (a.url for a in now_playing.images if not a.is_artist_photo),
            now_playing.images[0].url if now_playing.images else "",
        )
        with self._lock:
            latest = self._conn.execute(
                "SELECT source, title, subtitle, played_at FROM plays"
                " ORDER BY played_at DESC, id DESC LIMIT 1"
            ).fetchone()
            if (
                latest is not None
                and latest[:3] == (now_playing.source, now_playing.title, now_playing.subtitle)
                and now - latest[3] < self.dedupe_window_seconds
            ):
                return

            self._conn.execute(
                "INSERT INTO plays"
                " (played_at, source, media_type, title, subtitle, album, artwork_url)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    now,
                    now_playing.source,
                    now_playing.media_type,
                    now_playing.title,
                    now_playing.subtitle,
                    now_playing.album,
                    artwork_url,
                ),
            )
            self._conn.execute(
                "DELETE FROM plays WHERE id NOT IN"
                " (SELECT id FROM plays ORDER BY played_at DESC, id DESC LIMIT ?)",
                (self.max_entries,),
            )
            self._conn.commit()

    def list(self, limit: int = 50) -> List[dict]:
        """Newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, played_at, source, media_type, title, subtitle, album,"
                " artwork_url FROM plays ORDER BY played_at DESC, id DESC LIMIT ?",
                (max(1, min(limit, self.max_entries)),),
            ).fetchall()
        return [
            {
                "id": row[0],
                "played_at": row[1],
                "source": row[2],
                "media_type": row[3],
                "title": row[4],
                "subtitle": row[5],
                "album": row[6],
                "has_artwork": bool(row[7]),
            }
            for row in rows
        ]

    def entry_artwork(self, entry_id: int) -> Optional[tuple]:
        """(artwork_url, media_type) for one entry, or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT artwork_url, media_type FROM plays WHERE id = ?", (entry_id,)
            ).fetchone()
        if row is None or not row[0]:
            return None
        return (row[0], row[1])

    def close(self) -> None:
        with self._lock:
            self._conn.close()
