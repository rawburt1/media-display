"""Config dataclasses for `idle.*` plugins (wallpaper sources shown on
outputs when nothing is playing)."""

from __future__ import annotations

import pydantic


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
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


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class PexelsWallpaperConfig:
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
    # Free API key from https://www.pexels.com/api/ - the same key works
    # for outputs.video's Pexels video clips too, if that's also enabled.
    api_key: str = ""


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class LocalWallpaperConfig:
    enabled: bool = False
    # Base directory - each immediate subdirectory is treated as one
    # "destination" (e.g. one folder per trip/location). One destination
    # is picked at random per batch, and batch_size pictures are picked at
    # random from within it (searched recursively, so nested subfolders
    # under a destination are included too) - pictures are never mixed
    # across destinations within the same batch.
    dir: str = "./wallpapers"
    # How often (in seconds) to pick a fresh destination/batch while idle.
    # Each output then independently rotates through that batch (in its
    # own random order) using the top-level rotation_interval_seconds.
    rotation_interval_seconds: int = 300
    # Number of pictures to pick per batch.
    batch_size: int = 15


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
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


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
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
    "local": LocalWallpaperConfig,
    "pexels": PexelsWallpaperConfig,
    "unsplash": UnsplashWallpaperConfig,
}
