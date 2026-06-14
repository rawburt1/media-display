"""Configuration loading: YAML file -> dataclasses."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Union

import yaml


@dataclasses.dataclass
class KodiConfig:
    enabled: bool = False
    host: str = ""
    port: int = 8080
    username: str = ""
    password: str = ""


@dataclasses.dataclass
class SonosConfig:
    enabled: bool = False
    speaker_ip: str = ""


@dataclasses.dataclass
class PixooConfig:
    enabled: bool = False
    ip: str = ""


@dataclasses.dataclass
class WebConfig:
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8090


@dataclasses.dataclass
class CacheConfig:
    dir: str = "./cache"


@dataclasses.dataclass
class FanartTvConfig:
    enabled: bool = False
    # Personal API key from https://fanart.tv/get-an-api-key/
    api_key: str = ""


@dataclasses.dataclass
class UnsplashWallpaperConfig:
    enabled: bool = False
    # Comma-separated list of search queries to pick wallpapers from while
    # nothing is playing, e.g. "nature,architecture,space".
    queries: str = ""
    # How often (in seconds) to switch to a new wallpaper while idle.
    rotation_interval_seconds: int = 300
    # Access key from https://unsplash.com/oauth/applications
    access_key: str = ""


@dataclasses.dataclass
class LoggingConfig:
    # Path to a log file. Empty (the default) means console-only logging.
    file: str = ""
    # Rotate the log file once it reaches this size (bytes).
    max_bytes: int = 1_000_000
    # Number of rotated backup files to keep.
    backup_count: int = 3


# Registries mapping config section names to their dataclass types. Adding a
# new source or output starts here.
SOURCE_CONFIG_TYPES: dict[str, type] = {
    "kodi": KodiConfig,
    "sonos": SonosConfig,
}

OUTPUT_CONFIG_TYPES: dict[str, type] = {
    "pixoo": PixooConfig,
    "web": WebConfig,
}

ENRICHER_CONFIG_TYPES: dict[str, type] = {
    "fanarttv": FanartTvConfig,
}

# Idle wallpaper sources: shown on outputs when nothing is playing.
IDLE_CONFIG_TYPES: dict[str, type] = {
    "unsplash": UnsplashWallpaperConfig,
}


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
    outputs: dict[str, Any]
    enrichers: dict[str, Any]
    idle: dict[str, Any]
    cache: CacheConfig
    logging: LoggingConfig

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

        sources = {
            name: SOURCE_CONFIG_TYPES[name](**values)
            for name, values in (raw.get("sources") or {}).items()
            if name in SOURCE_CONFIG_TYPES
        }
        outputs = {
            name: OUTPUT_CONFIG_TYPES[name](**values)
            for name, values in (raw.get("outputs") or {}).items()
            if name in OUTPUT_CONFIG_TYPES
        }
        enrichers = {
            name: ENRICHER_CONFIG_TYPES[name](**values)
            for name, values in (raw.get("enrichers") or {}).items()
            if name in ENRICHER_CONFIG_TYPES
        }
        idle = {
            name: IDLE_CONFIG_TYPES[name](**values)
            for name, values in (raw.get("idle") or {}).items()
            if name in IDLE_CONFIG_TYPES
        }

        return cls(
            poll_interval_seconds=raw.get("poll_interval_seconds", 5),
            rotation_interval_seconds=raw.get("rotation_interval_seconds", 30),
            priority=raw.get("priority", []),
            sources=sources,
            outputs=outputs,
            enrichers=enrichers,
            idle=idle,
            cache=CacheConfig(**(raw.get("cache") or {})),
            logging=LoggingConfig(**(raw.get("logging") or {})),
        )
