"""Config dataclasses for `enrichers.*` plugins."""

from __future__ import annotations

import dataclasses

import pydantic


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class DiscogsConfig:
    enabled: bool = False
    # Personal access token from https://www.discogs.com/settings/developers
    token: str = ""


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class FanartTvConfig:
    enabled: bool = False
    # Personal API key from https://fanart.tv/get-an-api-key/
    api_key: str = ""


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class LastFmConfig:
    enabled: bool = False
    # API key from https://www.last.fm/api/account/create (free).
    api_key: str = ""


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class MusicBrainzConfig:
    enabled: bool = False
    # No API key required; uses the free Cover Art Archive.


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class LibraryEnricherConfig:
    # No API key required; looks up the local MusicLibrary only (plus the
    # free Cover Art Archive for the actual cover image).
    enabled: bool = True


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class MediaDataWordcloudConfig:
    # Whether to render a lyrics word-cloud PNG for the playing track,
    # colored from its album art, once both are available in the local
    # media-data cache - stored next to the track's .lrc file (see
    # MediaDataStore.get_track_wordcloud). A separate switch from the
    # enricher's own `enabled` above, since this adds a real CPU cost per
    # newly-seen track (word-cloud layout) and an extra dependency (the
    # `wordcloud` package, which pulls in matplotlib) that album
    # art/artist photo caching alone doesn't need. Off by default.
    enabled: bool = False


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class MediaDataArtworkEnricherConfig:
    # Checks the local unified media-data cache (see
    # mediainfo/media_data_store.py, configured via the top-level
    # `mediadata:` section) for album art before other music enrichers
    # run - see mediainfo/enrichers/mediadata.py. No credentials of its
    # own; a cache miss falls through to a real MusicBrainz (free) /
    # Discogs (if enrichers.discogs.token is set) lookup.
    enabled: bool = False
    wordcloud: MediaDataWordcloudConfig = dataclasses.field(
        default_factory=MediaDataWordcloudConfig
    )


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
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


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class WikipediaConfig:
    enabled: bool = False
    # No API key required; uses the free Wikipedia REST API.


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class TmdbConfig:
    enabled: bool = False
    # Free credential from https://www.themoviedb.org/settings/api - either
    # kind works: the short v3 "API Key", or the long v4 "API Read Access
    # Token" (a JWT - detected automatically by its two dots and sent as a
    # Bearer header instead of a query param).
    api_key: str = ""
    # Off by default - one extra TMDb API call per new movie/TV item, to
    # populate NowPlaying.cast (used by the Cast/Crew Mosaic Display
    # Theme). TV credits are show-level (regular cast), not per-episode
    # guest stars.
    fetch_cast: bool = False
    # Cap on how many top-billed cast members to store.
    cast_size: int = 8


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class OmdbConfig:
    enabled: bool = False
    # Free API key from https://www.omdbapi.com/apikey.aspx
    api_key: str = ""


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class SonarrConfig:
    enabled: bool = False
    host: str = ""
    port: int = 8989
    # API key from Sonarr's Settings → General → Security.
    api_key: str = ""


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class RadarrConfig:
    enabled: bool = False
    host: str = ""
    port: int = 7878
    # API key from Radarr's Settings → General → Security.
    api_key: str = ""


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class LidarrConfig:
    enabled: bool = False
    host: str = ""
    port: int = 8686
    # API key from Lidarr's Settings → General → Security.
    api_key: str = ""
    # Cap on how many "<album> – <track>" entries to list in
    # NowPlaying.discography for a prolific artist.
    max_discography_items: int = 50


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class FingerprintConfig:
    enabled: bool = False
    # Host and port of a running vinyl_recognizer instance.
    host: str = "localhost"
    port: int = 8091
    # Only use recognition results from the last N seconds; older results
    # likely belong to a track that's no longer playing.
    max_age_seconds: int = 120


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class SvtConfig:
    # No API key required - uses SVT's public content API (contento.svt.se).
    enabled: bool = True
    # Optional Sonarr connection for resolving Swedish SVT titles to their
    # tvdb-id (which SVT's own API can't provide), so enrichers like thetvdb
    # and fanarttv can subsequently fetch proper artwork by id.
    sonarr_host: str = ""
    sonarr_port: int = 8989
    sonarr_api_key: str = ""


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class AiArtworkConfig:
    # Off by default - requires a local Stable-Diffusion-WebUI-API-
    # compatible instance the user has set up (and loaded a checkpoint
    # into) themselves; see mediainfo/enrichers/ai_artwork.py.
    enabled: bool = False
    host: str = "localhost"
    port: int = 7860
    steps: int = 20
    width: int = 512
    height: int = 512
    # Image generation can be slow depending on model/steps/hardware; this
    # bounds how long one enrichment call may block the orchestrator's
    # tick loop before giving up (see the enricher's module docstring).
    timeout_seconds: int = 120


# Registry mapping config section names to their dataclass types. Adding a
# new enricher starts here.
ENRICHER_CONFIG_TYPES: dict[str, type] = {
    "ai_artwork": AiArtworkConfig,
    "discogs": DiscogsConfig,
    "fanarttv": FanartTvConfig,
    "fingerprint": FingerprintConfig,
    "lastfm": LastFmConfig,
    "library": LibraryEnricherConfig,
    "lidarr": LidarrConfig,
    "mediadata": MediaDataArtworkEnricherConfig,
    "musicbrainz": MusicBrainzConfig,
    "omdb": OmdbConfig,
    "radarr": RadarrConfig,
    "sonarr": SonarrConfig,
    "svt": SvtConfig,
    "thetvdb": TheTvDbConfig,
    "tmdb": TmdbConfig,
    "wikipedia": WikipediaConfig,
}
