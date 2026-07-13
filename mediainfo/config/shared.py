"""Config dataclasses shared across plugin families (not tied to a single
source/output/enricher/idle plugin)."""

from __future__ import annotations

import dataclasses

import pydantic


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class LibraryConfig:
    # Local SQLite cache of artist/album/track metadata (external ids like
    # MusicBrainz mbids, and "claims" like cover art URLs or artist photos)
    # so the music enrichers (musicbrainz, fanarttv, discogs, lastfm) query
    # this first instead of repeating the same external API lookup for the
    # same artist/album/song across plays and process restarts.
    db_path: str = "./library/library.db"
    # How long a cached claim (e.g. a cover art URL, or "no cover art
    # found") stays valid before it's looked up again.
    max_age_days: int = 30


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class AuthConfig:
    # Off by default. When enabled, HTTP Basic Auth is required for the
    # web/config/info/feed/video/nest_hub outputs - but only for requests
    # whose source address is *not* an RFC1918 private-use (or loopback)
    # address, so your own LAN keeps working without a login prompt. The
    # common reason to turn this on is exposing one of these outputs
    # beyond your LAN (port-forwarding, a reverse proxy, a VPN you don't
    # fully trust, ...).
    enabled: bool = False
    username: str = ""
    # Stored hashed (see mediainfo.web_auth.hash_password) - set via
    # `python -m mediainfo set-password` or the config UI, which hash it
    # for you; there's no way to write a valid value here by hand.
    password: str = ""


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class HttpServerConfig:
    # The single HTTP server every Flask-based output (web/config/themes/
    # info/feed/video/nest_hub) shares - one process, one port, one
    # listener (see H1 in docs/architecture-usability-review-2026-07.md).
    # Each output still has its own `enabled` flag and mounts under its own
    # path prefix (outputs.web at "/", everything else at "/<name>", e.g.
    # "/config", "/themes" - see wiring.py) instead of owning a separate
    # port the way it used to.
    host: str = "0.0.0.0"
    port: int = 8090


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class CacheConfig:
    dir: str = "./cache"
    max_age_days: int = 30
    # Idle wallpapers (Unsplash, Last.fm scrobble history, etc.) are purged
    # on a much shorter schedule than now-playing artwork, since they're
    # decorative and easily refetched rather than tied to a specific item.
    idle_max_age_hours: int = 48
    # Reject downloads smaller than this - low-res thumbnails (e.g. a
    # fallback icon some APIs return when they have no real artwork)
    # aren't worth displaying full-screen and aren't worth the disk space
    # either. Set to 0 to disable the check entirely. Doesn't apply to
    # manual artwork overrides (see OverridesConfig) - those are a
    # deliberate choice, not a downloaded fallback.
    min_width: int = 640
    min_height: int = 480
    # Music artwork (album art, artist photos) is never purged by age (see
    # mediainfo.cache.ImageCache's music_dir) - re-fetching the same
    # handful of albums/artists every time they're replayed isn't worth
    # it. Still bounded by total size to avoid unbounded disk growth on a
    # small device over years: once this is exceeded, the
    # least-recently-used files are evicted first. Set to 0 to disable the
    # cap entirely (the old unbounded behavior).
    max_music_mb: int = 500


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class AlertConfig:
    # Off by default. When enabled, a webhook is POSTed once a source or
    # output has been continuously failing (e.g. a Pixoo64/Nest Hub
    # unreachable on the network, or a source like vinyl_recognizer that's
    # simply not running) for at least error_threshold_seconds - most chat
    # tools (Slack, Discord, ntfy.sh, healthchecks.io, ...) accept a plain
    # JSON POST, so no extra dependency is needed here.
    enabled: bool = False
    webhook_url: str = ""
    # How long a source or output must be continuously erroring before the
    # first alert fires for it.
    error_threshold_seconds: int = 300
    # Minimum time between repeat alerts for the same still-failing source
    # or output, so a long outage doesn't spam the webhook on every check.
    repeat_interval_seconds: int = 3600


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class OverridesConfig:
    # Manual per-title artwork pins, managed via the config UI's
    # "Overrides" page - see mediainfo/artwork_overrides.py.
    enabled: bool = True
    dir: str = "./overrides"


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class PostersConfig:
    # Static poster images stored in `dir`, matched per show by title and
    # optionally source (see mediainfo/poster_store.py).
    enabled: bool = True
    dir: str = "./posters"
    entries: list = dataclasses.field(default_factory=list)


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class HistoryConfig:
    # Persistent playback history (a self-hosted scrobble log across every
    # source) - browsable at the web output's /history page. See
    # mediainfo/history.py.
    enabled: bool = True
    db_path: str = "./library/history.db"
    # Oldest entries beyond this count are pruned on insert.
    max_entries: int = 1000
    # A repeat of the most recent entry within this window is not logged
    # again - covers a source blip that stops and resumes the same item.
    dedupe_window_seconds: int = 600


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class LoggingConfig:
    # Python logging level name: DEBUG, INFO, WARNING, ERROR, or CRITICAL.
    level: str = "INFO"
    # Path to a log file. Empty (the default) means console-only logging.
    file: str = ""
    # Rotate the log file once it reaches this size (bytes).
    max_bytes: int = 1_000_000
    # Number of rotated backup files to keep.
    backup_count: int = 3


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class MediaDataRefreshConfig:
    # When False, cached artwork is used forever once fetched - never
    # checked for staleness (still fetched once if missing). See
    # mediainfo/media_data_store.py.
    enabled: bool = True
    movies_days: int = 180
    series_days: int = 30
    # Longer than movies/series - a released album's art essentially never
    # changes, unlike a still-airing TV series' poster/fanart.
    music_days: int = 365


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class MediaDataConfig:
    # Unified on-disk artwork/lyrics/metadata cache (see
    # mediainfo/media_data_store.py), read by the opt-in
    # enrichers.mediadata / text_enrichers.mediadata plugins.
    path: str = "./mediadata"
    # Whether to prefer the local cache over an external re-check - True
    # (the default) means cached content is served immediately even when
    # stale; a refresh (see `refresh` below) happens (or is attempted)
    # afterwards rather than blocking the caller.
    cache_first: bool = True
    refresh: MediaDataRefreshConfig = dataclasses.field(default_factory=MediaDataRefreshConfig)
    # Total size cap across the whole store, in MB - like
    # cache.max_music_mb, content here isn't purged by age (a movie's
    # poster doesn't go stale the way idle wallpapers do), so this is the
    # backstop against unbounded growth on a small device as a library
    # grows over years (M2 in docs/architecture-usability-review-2026-07.md).
    # Once exceeded, whole least-recently-used items (a movie/series/
    # artist/album's entire folder) are evicted first. Set to 0 to disable
    # the cap entirely.
    max_disk_mb: int = 2000
