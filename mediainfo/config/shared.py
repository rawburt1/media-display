"""Config dataclasses shared across plugin families (not tied to a single
source/output/enricher/idle plugin)."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass
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


@dataclasses.dataclass
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
    password: str = ""


@dataclasses.dataclass
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


@dataclasses.dataclass
class AlertConfig:
    # Off by default. When enabled, a webhook is POSTed once an output has
    # been continuously failing (e.g. a Pixoo64 or Nest Hub unreachable on
    # the network) for at least error_threshold_seconds - most chat tools
    # (Slack, Discord, ntfy.sh, healthchecks.io, ...) accept a plain JSON
    # POST, so no extra dependency is needed here.
    enabled: bool = False
    webhook_url: str = ""
    # How long an output must be continuously erroring before the first
    # alert fires for it.
    error_threshold_seconds: int = 300
    # Minimum time between repeat alerts for the same still-failing output,
    # so a long outage doesn't spam the webhook on every check.
    repeat_interval_seconds: int = 3600


@dataclasses.dataclass
class OverridesConfig:
    # Manual per-title artwork pins, managed via the config UI's
    # "Overrides" page - see mediainfo/artwork_overrides.py.
    enabled: bool = True
    dir: str = "./overrides"


@dataclasses.dataclass
class LoggingConfig:
    # Python logging level name: DEBUG, INFO, WARNING, ERROR, or CRITICAL.
    level: str = "INFO"
    # Path to a log file. Empty (the default) means console-only logging.
    file: str = ""
    # Rotate the log file once it reaches this size (bytes).
    max_bytes: int = 1_000_000
    # Number of rotated backup files to keep.
    backup_count: int = 3
