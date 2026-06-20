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

import re
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple

_SCHEMA = """
CREATE TABLE IF NOT EXISTS artists (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    name_normalized TEXT NOT NULL,
    mbid TEXT,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY,
    artist_id INTEGER NOT NULL REFERENCES artists(id),
    title TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
    mbid TEXT,
    updated_at REAL NOT NULL,
    UNIQUE(artist_id, title)
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    artist_id INTEGER NOT NULL REFERENCES artists(id),
    title TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
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

# Tables with a name/title column that gets fuzzy-matched, and the
# normalized-column migration needed for each (see _ensure_normalized_columns).
_NORMALIZED_COLUMNS = {"artists": "name", "albums": "title", "tracks": "title"}


def normalize(text: str) -> str:
    """Fold a name/title down to a form that's tolerant of the kind of
    differences that crop up between sources reporting the same real-world
    artist/album/song: case, accents, "&" vs "and", and punctuation.
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("&", " and ")
    text = text.replace("'", "").replace("’", "")  # drop apostrophes, not split words
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


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
            self._ensure_normalized_columns()

    def _ensure_normalized_columns(self) -> None:
        """Migration for databases created before fuzzy matching existed:
        add the *_normalized column and backfill it from existing rows.
        No-op for a fresh database, where _SCHEMA already created the
        column - this only ever runs the ALTER/backfill once.
        """
        for table, base_col in _NORMALIZED_COLUMNS.items():
            norm_col = f"{base_col}_normalized"
            existing_cols = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if norm_col not in existing_cols:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {norm_col} TEXT")
                rows = self._conn.execute(f"SELECT id, {base_col} FROM {table}").fetchall()
                for row_id, value in rows:
                    self._conn.execute(
                        f"UPDATE {table} SET {norm_col} = ? WHERE id = ?",
                        (normalize(value), row_id),
                    )
            self._conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_{norm_col} ON {table}({norm_col})"
            )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- canonical entities --------------------------------------------

    def get_or_create_artist(self, name: str) -> int:
        normalized = normalize(name)
        return self._get_or_create(
            "artists",
            match={"name_normalized": normalized},
            insert={"name": name, "name_normalized": normalized},
        )

    def get_or_create_album(self, artist_id: int, title: str) -> int:
        normalized = normalize(title)
        return self._get_or_create(
            "albums",
            match={"artist_id": artist_id, "title_normalized": normalized},
            insert={"artist_id": artist_id, "title": title, "title_normalized": normalized},
        )

    def get_or_create_track(self, artist_id: int, title: str) -> int:
        normalized = normalize(title)
        return self._get_or_create(
            "tracks",
            match={"artist_id": artist_id, "title_normalized": normalized},
            insert={"artist_id": artist_id, "title": title, "title_normalized": normalized},
        )

    def _get_or_create(self, table: str, match: dict, insert: dict) -> int:
        where = " AND ".join(f"{c} = ?" for c in match)
        with self._lock:
            row = self._conn.execute(
                f"SELECT id FROM {table} WHERE {where}", list(match.values())
            ).fetchone()
            if row is not None:
                return row[0]

            columns = list(insert) + ["updated_at"]
            placeholders = ", ".join("?" for _ in columns)
            cursor = self._conn.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                list(insert.values()) + [time.time()],
            )
            self._conn.commit()
            assert cursor.lastrowid is not None  # guaranteed after a successful INSERT
            return cursor.lastrowid

    def find_artist(self, name: str) -> Optional[int]:
        """Look up an artist by name (fuzzy-matched) without creating one
        if it's missing."""
        normalized = normalize(name)
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM artists WHERE name_normalized = ?", (normalized,)
            ).fetchone()
        return row[0] if row else None

    def find_track(self, artist_id: int, title: str) -> Optional[int]:
        """Look up a track by artist+title (fuzzy-matched) without creating
        one if it's missing."""
        normalized = normalize(title)
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM tracks WHERE artist_id = ? AND title_normalized = ?",
                (artist_id, normalized),
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

    def random_albums(self, limit: int) -> List[Tuple[int, str, str, str]]:
        """Return up to `limit` random (album_id, artist name, album title,
        mbid) tuples for albums that have a known MusicBrainz id - used by
        the idle wallpaper source to show cover art from the library."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT albums.id, artists.name, albums.title, albums.mbid "
                "FROM albums JOIN artists ON artists.id = albums.artist_id "
                "WHERE albums.mbid IS NOT NULL AND albums.mbid != '' "
                "ORDER BY RANDOM() LIMIT ?",
                (limit,),
            ).fetchall()
        return [(row[0], row[1], row[2], row[3]) for row in rows]

    def artist_name(self, artist_id: int) -> Optional[str]:
        """Look up an artist's name by id - used by the config UI's
        library browser. Returns None if no such artist exists."""
        with self._lock:
            row = self._conn.execute(
                "SELECT name FROM artists WHERE id = ?", (artist_id,)
            ).fetchone()
        return row[0] if row else None

    def search(self, query: str, limit: int = 50) -> List[Tuple[int, str]]:
        """Return up to `limit` (artist_id, artist name) pairs whose name
        contains `query` (case/accent/punctuation-insensitive) - used by the
        config UI's library browser."""
        normalized = normalize(query)
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name FROM artists WHERE name_normalized LIKE ? ORDER BY name LIMIT ?",
                (f"%{normalized}%", limit),
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def albums_for_artist(self, artist_id: int) -> List[Tuple[int, str, Optional[str]]]:
        """Return (album_id, title, mbid) for every album by this artist."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, mbid FROM albums WHERE artist_id = ? ORDER BY title",
                (artist_id,),
            ).fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    def tracks_for_artist(self, artist_id: int) -> List[Tuple[int, str, Optional[str]]]:
        """Return (track_id, title, mbid) for every track by this artist."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, mbid FROM tracks WHERE artist_id = ? ORDER BY title",
                (artist_id,),
            ).fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    def stats(self) -> dict:
        """Summary counts for the config UI's library browser."""
        with self._lock:
            artists = self._conn.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
            albums = self._conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
            tracks = self._conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        return {"artists": artists, "albums": albums, "tracks": tracks}

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
