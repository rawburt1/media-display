"""Config dataclasses for `enrichers.*` plugins."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class DiscogsConfig:
    enabled: bool = False
    # Personal access token from https://www.discogs.com/settings/developers
    token: str = ""


@dataclasses.dataclass
class FanartTvConfig:
    enabled: bool = False
    # Personal API key from https://fanart.tv/get-an-api-key/
    api_key: str = ""


@dataclasses.dataclass
class LastFmConfig:
    enabled: bool = False
    # API key from https://www.last.fm/api/account/create (free).
    api_key: str = ""


@dataclasses.dataclass
class MusicBrainzConfig:
    enabled: bool = False
    # No API key required; uses the free Cover Art Archive.


@dataclasses.dataclass
class LibraryEnricherConfig:
    # No API key required; looks up the local MusicLibrary only (plus the
    # free Cover Art Archive for the actual cover image).
    enabled: bool = True


@dataclasses.dataclass
class TheTvDbConfig:
    enabled: bool = False
    # Project API key from https://thetvdb.com/dashboard/account/apikey
    api_key: str = ""
    # Only needed for "user-supported" API keys.
    pin: str = ""
    # When a title search for a show name is ambiguous (matches several
    # unrelated series - e.g. "Kingdom"), how many of the search results
    # to check episode-by-episode before giving up rather than guessing
    # wrong. Higher catches matches ranked further down by thetvdb's own
    # search, at the cost of more API calls for generic titles.
    max_search_candidates: int = 5


@dataclasses.dataclass
class WikipediaConfig:
    enabled: bool = False
    # No API key required; uses the free Wikipedia REST API.


@dataclasses.dataclass
class TmdbConfig:
    enabled: bool = False
    # Free credential from https://www.themoviedb.org/settings/api - either
    # kind works: the short v3 "API Key", or the long v4 "API Read Access
    # Token" (a JWT - detected automatically by its two dots and sent as a
    # Bearer header instead of a query param).
    api_key: str = ""


@dataclasses.dataclass
class OmdbConfig:
    enabled: bool = False
    # Free API key from https://www.omdbapi.com/apikey.aspx
    api_key: str = ""


@dataclasses.dataclass
class SonarrConfig:
    enabled: bool = False
    host: str = ""
    port: int = 8989
    # API key from Sonarr's Settings → General → Security.
    api_key: str = ""


@dataclasses.dataclass
class RadarrConfig:
    enabled: bool = False
    host: str = ""
    port: int = 7878
    # API key from Radarr's Settings → General → Security.
    api_key: str = ""


@dataclasses.dataclass
class LidarrConfig:
    enabled: bool = False
    host: str = ""
    port: int = 8686
    # API key from Lidarr's Settings → General → Security.
    api_key: str = ""
    # Cap on how many "<album> – <track>" entries to list in
    # NowPlaying.discography for a prolific artist.
    max_discography_items: int = 50


@dataclasses.dataclass
class FingerprintConfig:
    enabled: bool = False
    # Host and port of a running vinyl_recognizer instance.
    host: str = "localhost"
    port: int = 8091
    # Only use recognition results from the last N seconds; older results
    # likely belong to a track that's no longer playing.
    max_age_seconds: int = 120


@dataclasses.dataclass
class SvtConfig:
    # No API key required - uses SVT's public content API (contento.svt.se).
    enabled: bool = True
    # Optional Sonarr connection for resolving Swedish SVT titles to their
    # tvdb-id (which SVT's own API can't provide), so enrichers like thetvdb
    # and fanarttv can subsequently fetch proper artwork by id.
    sonarr_host: str = ""
    sonarr_port: int = 8989
    sonarr_api_key: str = ""


# Registry mapping config section names to their dataclass types. Adding a
# new enricher starts here.
ENRICHER_CONFIG_TYPES: dict[str, type] = {
    "discogs": DiscogsConfig,
    "fanarttv": FanartTvConfig,
    "fingerprint": FingerprintConfig,
    "lastfm": LastFmConfig,
    "library": LibraryEnricherConfig,
    "lidarr": LidarrConfig,
    "musicbrainz": MusicBrainzConfig,
    "omdb": OmdbConfig,
    "radarr": RadarrConfig,
    "sonarr": SonarrConfig,
    "svt": SvtConfig,
    "thetvdb": TheTvDbConfig,
    "tmdb": TmdbConfig,
    "wikipedia": WikipediaConfig,
}
