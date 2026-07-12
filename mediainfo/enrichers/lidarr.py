"""Lidarr enricher: adds the artist's other albums/songs and album art for
music, by matching the playing artist against Lidarr's own library (the
artists you actually track, rather than a public catalog).

This is a live, per-play lookup against the Lidarr API - distinct from
`mediainfo.lidarr_import`, which is a one-off bulk import of Lidarr's
MusicBrainz ids into the local MusicLibrary cache.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from mediainfo.config import LidarrConfig
from mediainfo.enrichers.arr_base import ArrEnricher
from mediainfo.models import NowPlaying

logger = logging.getLogger(__name__)


class LidarrEnricher(ArrEnricher):
    _STATUS_PATH = "/api/v1/system/status"

    def __init__(self, config: LidarrConfig):
        super().__init__(config)

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "music" or not now_playing.subtitle:
            return

        try:
            artist = self._find_artist(now_playing.subtitle)
            if artist is None:
                return

            albums = self._get("/api/v1/album", params={"artistId": artist["id"]}) or []

            self._append_album_art(now_playing, albums)
            now_playing.discography = self._build_discography(artist["id"], albums)
        except Exception:
            logger.exception("Lidarr enrichment error")

    def _find_artist(self, name: str) -> Optional[dict]:
        artists = self._get("/api/v1/artist") or []
        return self._find_by_exact_title(artists, name, "artistName")

    def _append_album_art(self, now_playing: NowPlaying, albums: list) -> None:
        match = self._find_by_exact_title(albums, now_playing.album, "title")
        images = (match or {}).get("images") or []
        self._append_image(now_playing, images, "cover", "Album (Lidarr)")

    def _build_discography(self, artist_id: int, albums: list) -> List[str]:
        entries: List[str] = []
        cap = self.config.max_discography_items
        albums_by_id = {a["id"]: a.get("title", "") for a in albums if a.get("id") is not None}

        tracks = self._get("/api/v1/track", params={"artistId": artist_id}) or []
        for track in tracks:
            if len(entries) >= cap:
                break
            album_title = albums_by_id.get(track.get("albumId"), "")
            title = track.get("title") or ""
            if not title:
                continue
            entries.append(f"{album_title} – {title}" if album_title else title)

        return entries
