"""Shared data model for "now playing" media information."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Artwork:
    """A single image that can be shown for a NowPlaying item."""

    url: str
    # Optional (username, password) needed to fetch this URL, if its host
    # requires the same auth as the source's API (e.g. Kodi).
    auth: Optional[Tuple[str, str]] = None
    # Human-readable description, e.g. "Poster (fanart.tv)" - used for
    # logging and shown in the web UI.
    label: str = ""


@dataclass
class NowPlaying:
    """A snapshot of what a source is currently playing."""

    source: str
    media_type: str  # "music" | "movie" | "episode" | "game"
    title: str
    subtitle: str = ""
    # Album name, for music (used to look up artwork by name when no
    # MusicBrainz id is available, e.g. for Sonos).
    album: str = ""
    images: List[Artwork] = field(default_factory=list)
    # External ids for enrichers, e.g. {"tmdb": "603", "tvdb": "...", "imdb": "tt0133093"}
    ids: Dict[str, str] = field(default_factory=dict)
    # Season number, for episodes (used to match fanart.tv season posters).
    season: Optional[int] = None
    # Release year, for movies (used by the Ulanzi text output).
    year: Optional[int] = None
    # Bio/plot summary text, e.g. from the Wikipedia enricher.
    summary: str = ""
    # Studio/network that produced the movie or TV series, e.g. from the
    # Radarr/Sonarr enrichers.
    studio: str = ""
    # Genres, e.g. from the Radarr enricher.
    genres: List[str] = field(default_factory=list)
    # Other albums/songs by the playing artist, e.g. from the Lidarr
    # enricher - "<album> - <track>" pairs, in no particular order.
    discography: List[str] = field(default_factory=list)

    @property
    def identity(self) -> tuple:
        """Fields that define whether two snapshots represent the same thing.

        Deliberately excludes `images`: identity means "what's playing", not
        "which image is currently shown" (so image rotation doesn't trigger
        re-enrichment or output updates as if the media had changed).
        """
        return (self.source, self.title, self.subtitle)
