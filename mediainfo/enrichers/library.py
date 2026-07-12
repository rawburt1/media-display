"""Library enricher: fills in album art for sources that don't report an
album at all (e.g. YouTube, whose media session has no album field).

Looks up the playing artist+song in the local MusicLibrary (populated via
`python -m mediainfo import-lidarr` or by the other music enrichers as
they resolve things by name) to find which album(s) it appears on, and
adds cover art for every one of them - a song that appears on more than
one release (the original studio album, a singles compilation, a
remaster, ...) gets art for all of them, not just one.

Does no external lookups of its own to find the track - only the (free,
unauthenticated) Cover Art Archive front-cover fetch for each album mbid
already on file goes over the network.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.enrichers.musicbrainz import fetch_front_cover
from mediainfo.models import Artwork, NowPlaying
from mediainfo.musiclibrary import MusicLibrary

logger = logging.getLogger(__name__)


class LibraryEnricher(ArtworkEnricher):
    capabilities = frozenset({"library"})

    def __init__(self, config=None, library: Optional[MusicLibrary] = None):
        self.config = config
        self.library = library

    def enrich(self, now_playing: NowPlaying) -> None:
        if self.library is None or now_playing.media_type != "music":
            return
        if now_playing.album or not now_playing.subtitle or not now_playing.title:
            return

        try:
            artist_id = self.library.find_artist(now_playing.subtitle)
            if artist_id is None:
                return
            track_id = self.library.find_track(artist_id, now_playing.title)
            if track_id is None:
                return

            albums = self.library.get_albums_for_track(track_id)
            if not albums:
                return

            # Only fill in the album name when it's unambiguous - a
            # comma-joined list of several album titles isn't a real album
            # name and would just confuse downstream name-based lookups.
            if len(albums) == 1:
                now_playing.album = albums[0][1]

            for _, title, mbid in albums:
                if not mbid:
                    continue
                cover_url = fetch_front_cover(mbid)
                if cover_url and not any(img.url == cover_url for img in now_playing.images):
                    now_playing.images.append(
                        Artwork(url=cover_url, label=f"Album art (Library): {title}")
                    )
        except Exception:
            logger.exception("Library enrichment error")

    def test_connection(self) -> Tuple[bool, str]:
        return True, "Local library - no network connection to test"
