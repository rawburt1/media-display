"""Config dataclasses for `idle.*` plugins (wallpaper sources shown on
outputs when nothing is playing)."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class UnsplashWallpaperConfig:
    enabled: bool = False
    # Comma-separated list of search queries to pick wallpapers from while
    # nothing is playing, e.g. "nature,architecture,space".
    queries: str = ""
    # How often (in seconds) to download a fresh batch of wallpapers while
    # idle. Each output then independently rotates through that batch (in
    # its own random order) using the top-level rotation_interval_seconds.
    rotation_interval_seconds: int = 300
    # Number of wallpapers to download per batch.
    batch_size: int = 10
    # Access key from https://unsplash.com/oauth/applications
    access_key: str = ""


@dataclasses.dataclass
class LastFmHistoryConfig:
    enabled: bool = False
    # Free API key from https://www.last.fm/api/account/create (same key
    # used by enrichers.lastfm, if that's also enabled).
    api_key: str = ""
    # Last.fm username whose scrobble history to show.
    username: str = ""
    # Number of recent scrobbles to fetch per refresh (deduplicated by
    # album art, so fewer wallpapers than this may actually be shown).
    batch_size: int = 10
    # How often (in seconds) to re-fetch scrobble history while idle. Each
    # output then independently rotates through that batch (in its own
    # random order) using the top-level rotation_interval_seconds.
    rotation_interval_seconds: int = 300


@dataclasses.dataclass
class LibraryIdleConfig:
    enabled: bool = False
    # Number of random albums (with a known MusicBrainz id) to show per
    # refresh while idle.
    batch_size: int = 10
    # How often (in seconds) to pick a fresh batch of albums while idle.
    # Each output then independently rotates through that batch (in its
    # own random order) using the top-level rotation_interval_seconds.
    rotation_interval_seconds: int = 300


# Registry mapping config section names to their dataclass types. Adding a
# new idle wallpaper source starts here.
IDLE_CONFIG_TYPES: dict[str, type] = {
    "lastfm": LastFmHistoryConfig,
    "library": LibraryIdleConfig,
    "unsplash": UnsplashWallpaperConfig,
}
