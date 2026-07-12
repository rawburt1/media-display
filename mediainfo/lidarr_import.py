"""One-off importer: populate the local MusicLibrary from a Lidarr
instance's already-verified artist/album/track metadata, via
`python -m mediainfo import-lidarr`.

Lidarr's artist/album/track records carry MusicBrainz ids
(foreignArtistId / foreignAlbumId / foreignRecordingId) for everything in
its library, matched by the user's own curation - importing them lets the
musicbrainz/fanarttv/discogs/lastfm enrichers skip a name-based
MusicBrainz lookup entirely for anything already in Lidarr.
"""

from __future__ import annotations

import dataclasses
import logging

import requests

from mediainfo.musiclibrary import MusicLibrary

logger = logging.getLogger(__name__)

_TIMEOUT = 30


@dataclasses.dataclass
class ImportStats:
    artists: int = 0
    albums: int = 0
    tracks: int = 0
    failed_artists: int = 0


def import_from_lidarr(library: MusicLibrary, base_url: str, api_key: str) -> ImportStats:
    base_url = base_url.rstrip("/")
    headers = {"X-Api-Key": api_key}
    stats = ImportStats()

    response = requests.get(f"{base_url}/api/v1/artist", headers=headers, timeout=_TIMEOUT)
    response.raise_for_status()
    artists = response.json()

    for artist in artists:
        name = artist.get("artistName")
        lidarr_artist_id = artist.get("id")
        if not name or lidarr_artist_id is None:
            continue

        try:
            albums, tracks = _import_artist(
                library, base_url, headers, name, lidarr_artist_id, artist
            )
        except Exception:
            logger.exception("Failed to import %r from Lidarr; skipping", name)
            stats.failed_artists += 1
            continue

        stats.artists += 1
        stats.albums += albums
        stats.tracks += tracks
        logger.info("Imported %r: %d album(s), %d track(s)", name, albums, tracks)

    return stats


def _import_artist(
    library: MusicLibrary,
    base_url: str,
    headers: dict,
    name: str,
    lidarr_artist_id: int,
    artist: dict,
) -> tuple[int, int]:
    artist_id = library.get_or_create_artist(name)
    mbid = artist.get("foreignArtistId")
    if mbid:
        library.set_mbid("artist", artist_id, mbid)

    album_count = 0
    albums_by_lidarr_id: dict[int, int] = {}
    response = requests.get(
        f"{base_url}/api/v1/album",
        params={"artistId": lidarr_artist_id},
        headers=headers,
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    for album in response.json():
        title = album.get("title")
        lidarr_album_id = album.get("id")
        if not title or lidarr_album_id is None:
            continue
        album_id = library.get_or_create_album(artist_id, title)
        album_mbid = album.get("foreignAlbumId")
        if album_mbid:
            library.set_mbid("album", album_id, album_mbid)
        albums_by_lidarr_id[lidarr_album_id] = album_id
        album_count += 1

    track_count = 0
    response = requests.get(
        f"{base_url}/api/v1/track",
        params={"artistId": lidarr_artist_id},
        headers=headers,
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    for track in response.json():
        title = track.get("title")
        if not title:
            continue
        track_id = library.get_or_create_track(artist_id, title)
        track_mbid = track.get("foreignRecordingId")
        if track_mbid:
            library.set_mbid("track", track_id, track_mbid)

        linked_album_id = albums_by_lidarr_id.get(track.get("albumId"))
        if linked_album_id is not None:
            library.link_track_album(track_id, linked_album_id)

        track_count += 1

    return album_count, track_count
