"""Configuration loading: YAML file -> dataclasses.

Split into one module per plugin family (sources/outputs/enrichers/idle)
plus shared.py for cross-cutting config (cache/library/logging/auth) -
this module re-exports all of them so existing `from mediainfo.config
import X` call sites are unaffected by the split.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any, Union

import yaml

_logger = logging.getLogger(__name__)

from mediainfo.config.enrichers import (
    ENRICHER_CONFIG_TYPES,
    DiscogsConfig,
    FanartTvConfig,
    FingerprintConfig,
    LastFmConfig,
    LibraryEnricherConfig,
    LidarrConfig,
    MusicBrainzConfig,
    OmdbConfig,
    RadarrConfig,
    SonarrConfig,
    SvtConfig,
    TheTvDbConfig,
    TmdbConfig,
    WikipediaConfig,
)
from mediainfo.config.idle import (
    IDLE_CONFIG_TYPES,
    LastFmHistoryConfig,
    LibraryIdleConfig,
    LocalWallpaperConfig,
    PexelsWallpaperConfig,
    UnsplashWallpaperConfig,
)
from mediainfo.config.outputs import (
    OUTPUT_CONFIG_TYPES,
    ConfigUiConfig,
    FeedConfig,
    FolderConfig,
    InfoConfig,
    MqttConfig,
    NestHubConfig,
    PixooConfig,
    UlanziConfig,
    VideoOutputConfig,
    WebConfig,
)
from mediainfo.config.shared import (
    AlertConfig,
    AuthConfig,
    CacheConfig,
    LibraryConfig,
    LoggingConfig,
    OverridesConfig,
)
from mediainfo.config.sources import (
    SOURCE_CONFIG_TYPES,
    AppleTvConfig,
    ChromecastConfig,
    EmbyConfig,
    HomeAssistantConfig,
    JellyfinConfig,
    KodiConfig,
    PlexConfig,
    Ps5Config,
    ShieldConfig,
    SonosConfig,
    SpotifyConfig,
    VinylConfig,
    YoutubeConfig,
)

__all__ = [
    "AlertConfig",
    "AppleTvConfig",
    "AuthConfig",
    "CacheConfig",
    "ChromecastConfig",
    "Config",
    "ConfigUiConfig",
    "DiscogsConfig",
    "EmbyConfig",
    "ENRICHER_CONFIG_TYPES",
    "FanartTvConfig",
    "FeedConfig",
    "FolderConfig",
    "HomeAssistantConfig",
    "IDLE_CONFIG_TYPES",
    "InfoConfig",
    "JellyfinConfig",
    "KodiConfig",
    "LastFmConfig",
    "LastFmHistoryConfig",
    "LibraryConfig",
    "LibraryEnricherConfig",
    "LibraryIdleConfig",
    "LidarrConfig",
    "LocalWallpaperConfig",
    "LoggingConfig",
    "MqttConfig",
    "MusicBrainzConfig",
    "NestHubConfig",
    "OmdbConfig",
    "OUTPUT_CONFIG_TYPES",
    "OverridesConfig",
    "PexelsWallpaperConfig",
    "PixooConfig",
    "PlexConfig",
    "Ps5Config",
    "RadarrConfig",
    "ShieldConfig",
    "SonarrConfig",
    "SonosConfig",
    "SOURCE_CONFIG_TYPES",
    "SpotifyConfig",
    "TheTvDbConfig",
    "TmdbConfig",
    "UlanziConfig",
    "UnsplashWallpaperConfig",
    "VideoOutputConfig",
    "VinylConfig",
    "WebConfig",
    "WikipediaConfig",
    "YoutubeConfig",
]


@dataclasses.dataclass
class Config:
    poll_interval_seconds: int
    # How often (in seconds) to switch to the next image for the currently
    # playing item, when more than one is available. Actual rotation is only
    # checked on poll ticks, so this is effectively rounded up to the nearest
    # multiple of poll_interval_seconds.
    rotation_interval_seconds: int
    priority: list[str]
    sources: dict[str, Any]
    # Each output type maps to a list of configs, so the same output type
    # (e.g. "web" or "ulanzi") can be configured multiple times to run
    # several instances side by side.
    outputs: dict[str, list[Any]]
    enrichers: dict[str, Any]
    idle: dict[str, Any]
    cache: CacheConfig
    library: LibraryConfig
    logging: LoggingConfig
    auth: AuthConfig
    # Backoff for sources whose device/service couldn't be reached - see
    # MediaSource.last_poll_failed. Delay starts at backoff_initial_seconds,
    # doubles after each consecutive failure, and is capped at
    # backoff_max_seconds.
    backoff_initial_seconds: int = 30
    backoff_max_seconds: int = 300
    # How long (in seconds) to tolerate a source reporting "nothing
    # playing" before actually switching outputs to idle, while something
    # was already playing - covers a source briefly reporting no active
    # session for a single poll or two during normal playback (e.g.
    # Kodi's active-player list momentarily empty around a scene
    # transition) without flashing every output to idle and back.
    nothing_playing_grace_seconds: float = 2
    alerts: AlertConfig = dataclasses.field(default_factory=AlertConfig)
    overrides: OverridesConfig = dataclasses.field(default_factory=OverridesConfig)
    # Order to try enabled idle wallpaper sources in (e.g. ["pexels",
    # "local", "unsplash"]) - mirrors the top-level `priority` list above,
    # but for idle sources. Any enabled idle source not listed here is
    # tried last, in the order it appears under `idle:`. Leave empty (the
    # default) to just use that config.yaml order for everyone.
    idle_priority: list[str] = dataclasses.field(default_factory=list)
    # "priority" (default): try idle sources in idle_priority order, use
    # the first one with wallpapers available - never mixed with another
    # source's pictures in the same batch. "random": same "use exactly one
    # source, never mixed" rule, but a source is picked at random each
    # batch instead of always preferring the highest-priority one.
    idle_mode: str = "priority"

    @classmethod
    def load(cls, path: Union[str, Path]) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found: {path}. "
                "Copy config.example.yaml to config.yaml and fill in your settings."
            )

        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "Config":
        """Build a Config from an already-parsed YAML dict.

        Split out from `load()` so callers that already hold a parsed dict
        (e.g. the `config` output's validate-before-save logic) can build
        and validate a Config without writing it to a file first.
        """
        sources = {}
        for name, values in (raw.get("sources") or {}).items():
            if name not in SOURCE_CONFIG_TYPES:
                _logger.warning(
                    "Unknown source plugin %r in config — ignored. Check for typos.", name
                )
                continue
            sources[name] = SOURCE_CONFIG_TYPES[name](**values)

        outputs: dict[str, list[Any]] = {}
        for name, value in (raw.get("outputs") or {}).items():
            if name not in OUTPUT_CONFIG_TYPES:
                _logger.warning(
                    "Unknown output plugin %r in config — ignored. Check for typos.", name
                )
                continue
            config_cls = OUTPUT_CONFIG_TYPES[name]
            entries = value if isinstance(value, list) else [value]
            outputs[name] = [config_cls(**entry) for entry in entries]

        enrichers = {}
        for name, values in (raw.get("enrichers") or {}).items():
            if name not in ENRICHER_CONFIG_TYPES:
                _logger.warning(
                    "Unknown enricher plugin %r in config — ignored. Check for typos.", name
                )
                continue
            enrichers[name] = ENRICHER_CONFIG_TYPES[name](**values)

        idle = {}
        for name, values in (raw.get("idle") or {}).items():
            if name not in IDLE_CONFIG_TYPES:
                _logger.warning(
                    "Unknown idle wallpaper source %r in config — ignored. Check for typos.", name
                )
                continue
            idle[name] = IDLE_CONFIG_TYPES[name](**values)

        return cls(
            poll_interval_seconds=raw.get("poll_interval_seconds", 5),
            rotation_interval_seconds=raw.get("rotation_interval_seconds", 30),
            priority=raw.get("priority", []),
            sources=sources,
            outputs=outputs,
            enrichers=enrichers,
            idle=idle,
            cache=CacheConfig(**(raw.get("cache") or {})),
            library=LibraryConfig(**(raw.get("library") or {})),
            logging=LoggingConfig(**(raw.get("logging") or {})),
            auth=AuthConfig(**(raw.get("auth") or {})),
            backoff_initial_seconds=raw.get("backoff_initial_seconds", 30),
            backoff_max_seconds=raw.get("backoff_max_seconds", 300),
            nothing_playing_grace_seconds=raw.get("nothing_playing_grace_seconds", 2),
            alerts=AlertConfig(**(raw.get("alerts") or {})),
            overrides=OverridesConfig(**(raw.get("overrides") or {})),
            idle_priority=raw.get("idle_priority", []),
            idle_mode=raw.get("idle_mode", "priority"),
        )
