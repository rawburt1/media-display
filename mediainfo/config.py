"""Configuration loading: YAML file -> dataclasses."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Union

import yaml


@dataclasses.dataclass
class AppleTvConfig:
    enabled: bool = False
    # IP address or hostname of the Apple TV.
    host: str = ""
    # Credentials obtained by running:
    #   python -m mediainfo auth appletv --config config.yaml
    # Companion is the primary protocol for tvOS 15+.
    companion_credentials: str = ""
    # MRP is used for older Apple TV hardware or tvOS < 15.
    mrp_credentials: str = ""
    # AirPlay credentials (optional, rarely needed for now-playing).
    airplay_credentials: str = ""


@dataclasses.dataclass
class EmbyConfig:
    enabled: bool = False
    host: str = ""
    port: int = 8096
    # API key from Dashboard → Advanced → API Keys → New API Key.
    api_key: str = ""


@dataclasses.dataclass
class JellyfinConfig:
    enabled: bool = False
    host: str = ""
    port: int = 8096
    # API key from Dashboard → Advanced → API Keys → New API Key.
    api_key: str = ""


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
    # Speaker names or IP addresses to ignore (e.g. speakers in rooms where
    # you don't want to trigger the display). Names match what's shown in
    # the Sonos app.
    blacklist: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class SpotifyConfig:
    enabled: bool = False
    # From https://developer.spotify.com/dashboard — create a free app.
    client_id: str = ""
    client_secret: str = ""
    # Must match the redirect URI registered in the Spotify dashboard.
    redirect_uri: str = "http://localhost:8888/callback"
    # Where to cache the OAuth token between restarts.
    cache_path: str = "./spotify_cache/token.json"


@dataclasses.dataclass
class VinylConfig:
    enabled: bool = False
    # Host/port of the vinyl_recognizer service (runs on the machine the
    # Behringer UCA202 is connected to).
    host: str = ""
    port: int = 8091


@dataclasses.dataclass
class ShieldConfig:
    enabled: bool = False
    # IP address of the Android TV device (e.g. Nvidia Shield).
    host: str = ""
    # ADB debugging port (Settings -> Device Preferences -> Developer
    # options -> enable "USB debugging" and "Network debugging").
    port: int = 5555
    # Path to the ADB private key (a matching `.pub` file is used too).
    # Generated automatically on first run if missing - accept the resulting
    # authorization prompt on the device's screen.
    adb_key_path: str = "./adb_keys/shield"


@dataclasses.dataclass
class PlexConfig:
    enabled: bool = False
    host: str = ""
    port: int = 32400
    # See https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/
    token: str = ""


@dataclasses.dataclass
class PixooConfig:
    enabled: bool = False
    ip: str = ""
    # Optional image transforms applied before the image is sent to the
    # display.  See config.example.yaml for the full list of available
    # transforms and their parameters.
    transforms: list = dataclasses.field(default_factory=list)
    # When set, save a 512×512 nearest-neighbour preview of the final
    # 64×64 image here after each update (useful for visual QA).
    preview_path: str = ""


@dataclasses.dataclass
class WebConfig:
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8090
    transforms: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class InfoConfig:
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8093
    # Image transforms applied before display. Left empty by default so
    # this output shows artwork at its original (high) resolution, unlike
    # outputs aimed at small physical displays.
    transforms: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class FeedConfig:
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8086
    # Feed channel title shown in podcast/RSS apps.
    title: str = "Now Playing"
    # Maximum number of entries to keep in memory (oldest are discarded).
    max_items: int = 50


@dataclasses.dataclass
class FolderConfig:
    enabled: bool = False
    # Directory that mirrors the album art / fanart / posters for whatever
    # is currently playing. Replaced whenever the item changes, and cleared
    # while idle.
    dir: str = "./artwork"
    transforms: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class NestHubConfig:
    enabled: bool = False
    # IP address of the Google Nest Hub (or other Cast-compatible display).
    device_ip: str = ""
    # This machine's LAN address, so the Nest Hub can fetch the image being
    # cast (Cast devices load media via HTTP URL, not a direct push).
    server_host: str = ""
    # Port for the small built-in HTTP server that serves the current
    # image to the Nest Hub. Must be reachable from the device.
    server_port: int = 8092
    transforms: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class UlanziConfig:
    enabled: bool = False
    # IP address of the Ulanzi TC001 (or other AWTRIX3 device).
    device_ip: str = ""
    # Name of the AWTRIX3 "custom app" used to show now-playing text.
    app_name: str = "now_playing"
    # Optional HTTP basic auth, if configured in AWTRIX3's settings.
    username: str = ""
    password: str = ""


@dataclasses.dataclass
class MqttConfig:
    enabled: bool = False
    # Hostname or IP of the MQTT broker.
    host: str = "localhost"
    port: int = 1883
    # Topic to publish now-playing events to.
    topic: str = "mediainfo/now_playing"
    # MQTT client identifier (must be unique per broker connection).
    client_id: str = "mediainfo"
    # Optional broker credentials (leave blank if auth is not configured).
    username: str = ""
    password: str = ""
    # QoS level: 0 = at most once, 1 = at least once, 2 = exactly once.
    qos: int = 0
    # Retain the last published message so new subscribers immediately see
    # the current state.
    retain: bool = True


@dataclasses.dataclass
class VideoOutputConfig:
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8091
    # Primary video source: "pexels" or "pixabay".
    source: str = "pexels"
    # Comma-separated search queries; one is chosen at random per refresh.
    queries: str = "nature,ocean,mountains"
    # How often (seconds) to fetch a fresh video batch while idle.
    refresh_interval_seconds: int = 3600
    # Number of videos to request per batch (Pixabay caps at 20).
    batch_size: int = 15
    # API key for https://www.pexels.com/api/
    pexels_api_key: str = ""
    # API key for https://pixabay.com/api/docs/ (used when source = "pixabay")
    pixabay_api_key: str = ""


@dataclasses.dataclass
class CacheConfig:
    dir: str = "./cache"
    max_age_days: int = 30


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
class TheTvDbConfig:
    enabled: bool = False
    # Project API key from https://thetvdb.com/dashboard/account/apikey
    api_key: str = ""
    # Only needed for "user-supported" API keys.
    pin: str = ""


@dataclasses.dataclass
class WikipediaConfig:
    enabled: bool = False
    # No API key required; uses the free Wikipedia REST API.


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
    "appletv": AppleTvConfig,
    "emby": EmbyConfig,
    "jellyfin": JellyfinConfig,
    "kodi": KodiConfig,
    "plex": PlexConfig,
    "shield": ShieldConfig,
    "sonos": SonosConfig,
    "spotify": SpotifyConfig,
    "vinyl": VinylConfig,
}

OUTPUT_CONFIG_TYPES: dict[str, type] = {
    "feed": FeedConfig,
    "folder": FolderConfig,
    "info": InfoConfig,
    "mqtt": MqttConfig,
    "nest_hub": NestHubConfig,
    "pixoo": PixooConfig,
    "ulanzi": UlanziConfig,
    "video": VideoOutputConfig,
    "web": WebConfig,
}

ENRICHER_CONFIG_TYPES: dict[str, type] = {
    "discogs": DiscogsConfig,
    "fanarttv": FanartTvConfig,
    "lastfm": LastFmConfig,
    "musicbrainz": MusicBrainzConfig,
    "thetvdb": TheTvDbConfig,
    "wikipedia": WikipediaConfig,
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
    # Each output type maps to a list of configs, so the same output type
    # (e.g. "web" or "ulanzi") can be configured multiple times to run
    # several instances side by side.
    outputs: dict[str, list[Any]]
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
        outputs: dict[str, list[Any]] = {}
        for name, value in (raw.get("outputs") or {}).items():
            if name not in OUTPUT_CONFIG_TYPES:
                continue
            config_cls = OUTPUT_CONFIG_TYPES[name]
            entries = value if isinstance(value, list) else [value]
            outputs[name] = [config_cls(**entry) for entry in entries]
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
