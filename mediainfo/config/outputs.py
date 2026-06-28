"""Config dataclasses for `outputs.*` plugins."""

from __future__ import annotations

import dataclasses


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
    # Image-change transition variants to exclude, e.g. [slide-left, zoom].
    # All variants (fade, slide-left, slide-right, slide-up, slide-down,
    # zoom) are used by default, picked at random per image change.
    transition_exclude: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class InfoConfig:
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8093
    # Image transforms applied before display. Left empty by default so
    # this output shows artwork at its original (high) resolution, unlike
    # outputs aimed at small physical displays.
    transforms: list = dataclasses.field(default_factory=list)
    # Image-change transition variants to exclude - see WebConfig above.
    transition_exclude: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class ConfigUiConfig:
    enabled: bool = False
    # Bind address for the config UI server.  Defaults to 127.0.0.1 (loopback
    # only) so it isn't reachable from the LAN without an explicit choice.
    # Set to 0.0.0.0 to allow access from other machines — required when
    # running inside Docker and accessing from the host.  See SECURITY.md.
    host: str = "127.0.0.1"
    port: int = 8094
    # "form" (default): the full editable config.yaml form + raw YAML
    # editor. "dashboard": a read-focused status overview of sources/
    # outputs/enrichers with filtering and a per-item connection test -
    # useful for running a second instance on another port dedicated to
    # "is everything working", without write access to config.yaml.
    ui: str = "form"


@dataclasses.dataclass
class FeedConfig:
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8086
    # Feed channel title shown in podcast/RSS apps.
    title: str = "Now Playing"


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
    # Image-change transition variants to exclude - see WebConfig above.
    transition_exclude: list = dataclasses.field(default_factory=list)


# Registry mapping config section names to their dataclass types. Adding a
# new output starts here.
OUTPUT_CONFIG_TYPES: dict[str, type] = {
    "config": ConfigUiConfig,
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
