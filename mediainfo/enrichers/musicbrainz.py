"""MusicBrainz Cover Art Archive enricher: adds album cover scans for music.

Also home to resolve_release_group_ids(), the shared MusicBrainz lookup
used by both this enricher and FanartTvEnricher's music branch (both need
the same artist+album -> (artist mbid, release-group mbid) resolution) -
backed by the local MusicLibrary so a name-based lookup only ever hits the
MusicBrainz API once per artist/album, no matter how many enrichers need
the result or how many times the album is replayed.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import requests

from mediainfo.config import MusicBrainzConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying
from mediainfo.musiclibrary import MusicLibrary

logger = logging.getLogger(__name__)

_MB_SEARCH_URL = "https://musicbrainz.org/ws/2/release-group/"
_CAA_FRONT_URL = "https://coverartarchive.org/release-group/{mbid}/front"
_USER_AGENT = "mediainfo/1.0 (personal use)"


def resolve_release_group_ids(
    library: Optional[MusicLibrary], artist: str, album: str
) -> Optional[Tuple[str, str]]:
    """Resolve (artist mbid, release-group mbid) for an artist+album name.

    Checks the local library first; only queries the MusicBrainz API on a
    cache miss (or if no library is configured), and stores the result
    (including a cached "nothing found" on a miss) so repeat lookups for
    the same artist/album never hit the network again.
    """
    if not artist or not album:
        return None

    if library is None:
        return _query_musicbrainz(artist, album)

    artist_id = library.get_or_create_artist(artist)
    album_id = library.get_or_create_album(artist_id, album)

    artist_mbid = library.get_mbid("artist", artist_id)
    album_mbid = library.get_mbid("album", album_id)
    if artist_mbid and album_mbid:
        return artist_mbid, album_mbid

    cached_miss = library.get_claim("album", album_id, "musicbrainz_resolved", "musicbrainz")
    if cached_miss == "":
        return None

    resolved = _query_musicbrainz(artist, album)
    if resolved is None:
        library.set_claim("album", album_id, "musicbrainz_resolved", "musicbrainz", "")
        return None

    artist_mbid, album_mbid = resolved
    library.set_mbid("artist", artist_id, artist_mbid)
    library.set_mbid("album", album_id, album_mbid)
    library.set_claim("album", album_id, "musicbrainz_resolved", "musicbrainz", "found")
    return artist_mbid, album_mbid


def fetch_front_cover(mbid: str) -> Optional[str]:
    """Return the final URL of a release-group's front cover from the
    Cover Art Archive, or None if not available."""
    url = _CAA_FRONT_URL.format(mbid=mbid)
    try:
        resp = requests.head(url, allow_redirects=True, timeout=10)
        if resp.status_code == 200:
            return resp.url
    except Exception:
        logger.debug("CAA request failed for %s", mbid)
    return None


def _query_musicbrainz(artist: str, album: str) -> Optional[Tuple[str, str]]:
    query = f'artist:"{artist}" AND release:"{album}"'
    try:
        params: dict = {"query": query, "fmt": "json", "limit": 5}
        response = requests.get(
            _MB_SEARCH_URL,
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=10,
        )
        response.raise_for_status()
        groups = response.json().get("release-groups") or []
    except Exception:
        logger.exception("MusicBrainz lookup failed for %r - %r", artist, album)
        return None

    if not groups:
        return None

    # Prefer a studio album over compilations/live recordings.
    group = next((g for g in groups if g.get("primary-type") == "Album"), groups[0])
    artist_credit = group.get("artist-credit") or []
    if not artist_credit:
        return None

    return artist_credit[0]["artist"]["id"], group["id"]


class MusicBrainzEnricher(ArtworkEnricher):
    name = "musicbrainz"
    config_class = MusicBrainzConfig
    capabilities = frozenset({"library"})

    def __init__(self, config: MusicBrainzConfig, library: Optional[MusicLibrary] = None):
        self.config = config
        self.library = library

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "music":
            return

        try:
            mbid = now_playing.ids.get("musicbrainzalbum")
            if not mbid:
                resolved = resolve_release_group_ids(
                    self.library, now_playing.subtitle, now_playing.album
                )
                if not resolved:
                    return
                mbid = resolved[1]

            image_url = fetch_front_cover(mbid)
            if image_url and not any(img.url == image_url for img in now_playing.images):
                now_playing.images.append(Artwork(url=image_url, label="Album art (MusicBrainz)"))
        except Exception:
            logger.exception("MusicBrainz enrichment error")

    def test_connection(self) -> Tuple[bool, str]:
        try:
            result = _query_musicbrainz("Queen", "A Night at the Opera")
            if result is not None:
                return True, "Resolved test query successfully"
            return False, "No match for test query (musicbrainz.org may be unreachable)"
        except Exception as exc:
            return False, f"Error: {exc}"
