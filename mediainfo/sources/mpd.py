"""Music Player Daemon (MPD) "now playing" source.

MPD speaks its own line-based text protocol (not JSON-RPC/REST), so this
uses python-mpd2 rather than hand-rolling a protocol client - see
requirements.txt.

Cover art: MPD has no concept of serving art over HTTP, only handing back
raw image bytes for the current song's file (embedded picture via
`readpicture`, or a same-folder cover file via `albumart`) - unlike every
other source in this codebase, which just returns a URL. To fit the
existing Artwork(url=...) model, fetched bytes are written to a small
on-disk cache once per track and exposed as a file:// URL (the same
mechanism mediainfo/artwork_overrides.py already relies on for local
files) rather than inventing an in-memory-bytes path through the whole
enrichment/caching pipeline.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Any, List, Optional

import mpd

from mediainfo.config import MpdConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# Where fetched cover art bytes are cached, keyed by a hash of the MPD file
# path so repeated polls of the same track reuse the same file instead of
# re-fetching (and re-encoding to disk) on every poll.
_ART_CACHE_DIR = Path(tempfile.gettempdir()) / "mediainfo_mpd_art"


def _art_cache_path(uri: str) -> Path:
    digest = hashlib.sha256(uri.encode("utf-8")).hexdigest()[:16]
    return _ART_CACHE_DIR / f"{digest}.jpg"


class MpdSource(MediaSource):
    config_class = MpdConfig
    name = "mpd"

    def __init__(self, config: MpdConfig):
        self.config = config
        # uri -> file:// URL, or "" when known to have no art - avoids
        # re-fetching art for the same track on every poll.
        self._art_cache: dict = {}

    def _connect(self) -> "mpd.MPDClient":
        client = mpd.MPDClient()
        client.timeout = self.config.timeout
        client.connect(self.config.host, self.config.port)
        if self.config.password:
            client.password(self.config.password)
        return client

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
        client = None
        try:
            client = self._connect()
            status = client.status()
            if status.get("state") != "play":
                return None

            song = client.currentsong()
            if not song:
                return None

            artist = song.get("artist", "") or ""
            album = song.get("album", "") or ""
            title = song.get("title", "") or song.get("file", "") or ""

            elapsed = status.get("elapsed")
            duration = status.get("duration") or song.get("duration")

            return NowPlaying(
                source=self.name,
                media_type="music",
                title=title,
                subtitle=artist,
                album=album,
                artist=artist,
                images=self._get_artwork(client, song.get("file", "")),
                position_seconds=float(elapsed) if elapsed is not None else None,
                duration_seconds=float(duration) if duration is not None else None,
            )
        except Exception:
            logger.exception("MPD source error")
            self.last_poll_failed = True
            return None
        finally:
            if client is not None:
                try:
                    client.close()
                    client.disconnect()
                except Exception:
                    pass

    def _get_artwork(self, client: Any, uri: str) -> List[Artwork]:
        if not uri:
            return []
        cached = self._art_cache.get(uri)
        if cached is not None:
            return [Artwork(url=cached, label="Album art (MPD)")] if cached else []

        url = self._fetch_and_cache_art(client, uri)
        self._art_cache[uri] = url or ""
        return [Artwork(url=url, label="Album art (MPD)")] if url else []

    @staticmethod
    def _fetch_and_cache_art(client: Any, uri: str) -> Optional[str]:
        """Try an embedded picture first (readpicture), then a same-folder
        cover file (albumart) - either, both, or neither may be supported
        depending on the MPD version and the track itself. Non-fatal: a
        missing cover just means existing artwork enrichers get a chance
        to find one instead, same as any other source with patchy artwork
        support.
        """
        for method_name in ("readpicture", "albumart"):
            try:
                result = getattr(client, method_name)(uri)
            except Exception:
                continue
            binary = (result or {}).get("binary")
            if binary:
                _ART_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                path = _art_cache_path(uri)
                path.write_bytes(binary)
                return f"file://{path}"
        return None
