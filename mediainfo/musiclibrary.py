"""Local SQLite cache of artist/album/track metadata.

Backs the music enrichers (musicbrainz, fanarttv, discogs, lastfm) so the
same artist/album/song doesn't trigger a repeat external API lookup on
every play - or every process restart, since this persists to disk.

MusicBrainz is treated as the source of truth for canonical entity ids
(mbids); other sources attach their own "claims" (a cover art URL, an
artist photo, ...) to the same artist/album/track once it's been resolved,
each tagged with where the value came from and when it was fetched so a
claim can expire and be re-fetched independently of the others.

A claim's value may be an empty string, which means "looked up before,
nothing found" - this negative-caching is what stops a wrong/missing
result from being re-queried on every single play.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

_SCHEMA = """
CREATE TABLE IF NOT EXISTS artists (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    mbid TEXT,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY,
    artist_id INTEGER NOT NULL REFERENCES artists(id),
    title TEXT NOT NULL,
    mbid TEXT,
    updated_at REAL NOT NULL,
    UNIQUE(artist_id, title)
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    artist_id INTEGER NOT NULL REFERENCES artists(id),
    title TEXT NOT NULL,
    mbid TEXT,
    updated_at REAL NOT NULL,
    UNIQUE(artist_id, title)
);

CREATE TABLE IF NOT EXISTS track_albums (
    track_id INTEGER NOT NULL REFERENCES tracks(id),
    album_id INTEGER NOT NULL REFERENCES albums(id),
    PRIMARY KEY (track_id, album_id)
);

CREATE TABLE IF NOT EXISTS source_claims (
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    source TEXT NOT NULL,
    value TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    PRIMARY KEY (entity_type, entity_id, field, source)
);
"""

_ENTITY_TABLES = {"artist": "artists", "album": "albums", "track": "tracks"}


class MusicLibrary:
    def __init__(self, db_path: str, max_age_days: float = 30):
        self.max_age_seconds = max_age_days * 86400
        self._lock = threading.Lock()
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- canonical entities --------------------------------------------

    def get_or_create_artist(self, name: str) -> int:
        return self._get_or_create("artists", {"name": name})

    def get_or_create_album(self, artist_id: int, title: str) -> int:
        return self._get_or_create("albums", {"artist_id": artist_id, "title": title})

    def get_or_create_track(self, artist_id: int, title: str) -> int:
        return self._get_or_create("tracks", {"artist_id": artist_id, "title": title})

    def _get_or_create(self, table: str, keys: dict) -> int:
        columns = list(keys)
        where = " AND ".join(f"{c} = ?" for c in columns)
        values = [keys[c] for c in columns]
        with self._lock:
            row = self._conn.execute(
                f"SELECT id FROM {table} WHERE {where}", values
            ).fetchone()
            if row is not None:
                return row[0]

            insert_columns = columns + ["updated_at"]
            placeholders = ", ".join("?" for _ in insert_columns)
            cursor = self._conn.execute(
                f"INSERT INTO {table} ({', '.join(insert_columns)}) VALUES ({placeholders})",
                values + [time.time()],
            )
            self._conn.commit()
            return cursor.lastrowid

    def find_artist(self, name: str) -> Optional[int]:
        """Look up an artist by name without creating one if it's missing."""
        with self._lock:
            row = self._conn.execute("SELECT id FROM artists WHERE name = ?", (name,)).fetchone()
        return row[0] if row else None

    def find_track(self, artist_id: int, title: str) -> Optional[int]:
        """Look up a track by artist+title without creating one if it's missing."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM tracks WHERE artist_id = ? AND title = ?", (artist_id, title)
            ).fetchone()
        return row[0] if row else None

    # -- track <-> album (a song can appear on more than one release) ----

    def link_track_album(self, track_id: int, album_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO track_albums (track_id, album_id) VALUES (?, ?)",
                (track_id, album_id),
            )
            self._conn.commit()

    def get_albums_for_track(self, track_id: int) -> List[Tuple[int, str, Optional[str]]]:
        """Return (album_id, title, mbid) for every album that contains this track."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT albums.id, albums.title, albums.mbid "
                "FROM albums JOIN track_albums ON track_albums.album_id = albums.id "
                "WHERE track_albums.track_id = ?",
                (track_id,),
            ).fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    # -- MusicBrainz ids (source of truth) -------------------------------

    def get_mbid(self, entity_type: str, entity_id: int) -> Optional[str]:
        table = _ENTITY_TABLES[entity_type]
        with self._lock:
            row = self._conn.execute(
                f"SELECT mbid FROM {table} WHERE id = ?", (entity_id,)
            ).fetchone()
        return row[0] if row and row[0] else None

    def set_mbid(self, entity_type: str, entity_id: int, mbid: str) -> None:
        table = _ENTITY_TABLES[entity_type]
        with self._lock:
            self._conn.execute(
                f"UPDATE {table} SET mbid = ?, updated_at = ? WHERE id = ?",
                (mbid, time.time(), entity_id),
            )
            self._conn.commit()

    # -- source claims (artwork urls, bios, ...) --------------------------

    def get_claim(self, entity_type: str, entity_id: int, field: str, source: str) -> Optional[str]:
        """Return the cached value, or None if there isn't one or it's stale.

        An empty string is a valid return value - it means "looked up
        before from this source, nothing found".
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT value, fetched_at FROM source_claims "
                "WHERE entity_type = ? AND entity_id = ? AND field = ? AND source = ?",
                (entity_type, entity_id, field, source),
            ).fetchone()
        if row is None:
            return None
        value, fetched_at = row
        if time.time() - fetched_at > self.max_age_seconds:
            return None
        return value

    def set_claim(self, entity_type: str, entity_id: int, field: str, source: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO source_claims (entity_type, entity_id, field, source, value, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(entity_type, entity_id, field, source) "
                "DO UPDATE SET value = excluded.value, fetched_at = excluded.fetched_at",
                (entity_type, entity_id, field, source, value, time.time()),
            )
            self._conn.commit()
