"""Discogs enricher: adds album cover art for music from the Discogs database.

Searches the Discogs master-release index by artist + album name, then appends
the canonical cover image.  Requires a personal access token (free) and both
`subtitle` (artist) and `album` to be set on the NowPlaying item — without a
precise album name the search is skipped to avoid adding artwork for the wrong
release.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import requests

from mediainfo.config import DiscogsConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying
from mediainfo.musiclibrary import MusicLibrary

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.discogs.com/database/search"
_USER_AGENT = "mediainfo/1.0 (personal use)"


def find_cover(token: str, artist: str, album: str) -> Optional[str]:
    """Look up Discogs cover art for an artist+album name - a pure,
    NowPlaying-independent function, so it's directly reusable outside
    the enricher (see mediainfo/media_data_store.py's album artwork
    fetch, which calls this the same way DiscogsEnricher._find_cover
    already did before this was extracted)."""
    # Masters represent canonical releases and have better, deduplicated artwork.
    url = _search(token, artist, album, "master")
    if url:
        return url
    # Fall back to individual releases for albums that have no master entry.
    return _search(token, artist, album, "release")


def _search(token: str, artist: str, album: str, result_type: str) -> Optional[str]:
    try:
        resp = requests.get(
            _SEARCH_URL,
            params={
                "type": result_type,
                "artist": artist,
                "release_title": album,
                "token": token,
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
    except Exception:
        logger.exception("Discogs search failed for %r – %r", artist, album)
        return None

    for result in results:
        cover = result.get("cover_image") or result.get("thumb") or ""
        if cover and _is_real_image(cover):
            return cover
    return None


class DiscogsEnricher(ArtworkEnricher):
    capabilities = frozenset({"library"})

    def __init__(self, config: DiscogsConfig, library: Optional[MusicLibrary] = None) -> None:
        self.config = config
        self.library = library

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "music":
            return

        artist = now_playing.subtitle
        album = now_playing.album
        if not artist or not album:
            return

        try:
            url = self._cover_for(artist, album)
            if url and not any(img.url == url for img in now_playing.images):
                now_playing.images.append(Artwork(url=url, label="Album art (Discogs)"))
        except Exception:
            logger.exception("Discogs enrichment error")

    def test_connection(self) -> Tuple[bool, str]:
        # A found vs. not-found cover are both "reachable" - the point is
        # to distinguish Discogs being unreachable/token invalid (an
        # exception) from a legitimate no-match for this specific query.
        try:
            url = find_cover(self.config.token, "Queen", "A Night at the Opera")
            if url:
                return True, "Found cover art for test query"
            return True, "Reached Discogs, no match for test query (token may still be invalid)"
        except Exception as exc:
            return False, f"Error: {exc}"

    def _cover_for(self, artist: str, album: str) -> Optional[str]:
        if self.library is None:
            return find_cover(self.config.token, artist, album)

        artist_id = self.library.get_or_create_artist(artist)
        album_id = self.library.get_or_create_album(artist_id, album)
        return self.library.get_or_fetch(
            "album",
            album_id,
            "cover_art_url",
            "discogs",
            lambda: find_cover(self.config.token, artist, album),
        )


def _is_real_image(url: str) -> bool:
    """Return False for empty strings and known Discogs placeholder images."""
    return bool(url) and not any(p in url for p in ("spacer.gif", "noimage", "default-release"))
