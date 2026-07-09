"""Config dataclasses for `outputs.*` plugins."""

from __future__ import annotations

import dataclasses

import pydantic


@dataclasses.dataclass
class _OutputFilterMixin:
    """Optional per-output content filter fields.

    All fields default to "no restriction" so existing configs that omit
    them keep their current behaviour unchanged.

    Rule evaluation order (first failing rule blocks the output):
      1. deny_media_types  — block if media_type is in the list
      2. deny_sources      — block if source is in the list
      3. allow_media_types — block if non-empty AND media_type not in list
      4. allow_sources     — block if non-empty AND source not in list
      5. active_hours      — block if current local time is outside window

    deny always beats allow.  active_hours wraps around midnight, e.g.
    "22:00-06:00" means active from 22:00 through 06:00 the next morning.
    """

    allow_media_types: list = dataclasses.field(default_factory=list)
    deny_media_types: list = dataclasses.field(default_factory=list)
    allow_sources: list = dataclasses.field(default_factory=list)
    deny_sources: list = dataclasses.field(default_factory=list)
    # When True, send the output to idle whenever the current media is
    # blocked by the rules above.  When False (default), the output simply
    # keeps showing whatever it last received.
    idle_when_filtered: bool = False
    # "HH:MM-HH:MM" local-time window during which this output is active.
    # Leave empty (default) for always-on.
    active_hours: str = ""
    # Cosmetic display name for this instance, shown instead of "#2" etc.
    # in the config UI when a type has multiple instances - has no effect
    # on behavior. Purely a UI convenience, not related to filtering.
    label: str = ""


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class PixooConfig(_OutputFilterMixin):
    enabled: bool = False
    ip: str = ""
    # LED matrix size in pixels.  64 for the Pixoo64 (default); 16 for the
    # Pixoo 16×16 Pixel Art LED Frame.  Affects both the image sent to the
    # device and the PicWidth field in the API payload.
    size: int = 64
    # Optional image transforms applied before the image is sent to the
    # display.  See config.example.yaml for the full list of available
    # transforms and their parameters.
    transforms: list = dataclasses.field(default_factory=list)
    # When set, save a 512×512 nearest-neighbour preview of the final image
    # here after each update (useful for visual QA).
    preview_path: str = ""
    # Turn the panel off during this daily window ("HH:MM-HH:MM", wraps
    # midnight, e.g. "23:00-07:00") and back on outside it. Unlike
    # active_hours (which switches to idle content), this actually powers
    # the LED matrix down. Empty = always on.
    screen_off_hours: str = ""
    # Daily brightness windows, one "HH:MM-HH:MM=<level>" string per entry
    # (e.g. "08:00-20:00=90", "20:00-08:00=15"). First matching window
    # wins; outside all windows the brightness is left alone. Level is
    # the Pixoo's native 0-100 range.
    brightness_schedule: list = dataclasses.field(default_factory=list)
    # How to pick the square crop before downscaling. "automatic" (default)
    # biases toward the top third for portrait sources (where poster faces/
    # titles usually sit) and centers otherwise; "center" always centers;
    # "poster_top" always biases toward the top (a no-op for
    # landscape/square sources). See mediainfo/led_image.py.
    crop_strategy: str = "automatic"
    # Number of colours in the final LED image's palette. Lower = bolder,
    # more "pixel art" blocks of colour; higher = more subtle gradients.
    palette_size: int = 24
    # Dithering applied during palette reduction: "none" (bold, clean
    # blocks - the default), "ordered" (subtle, structured), or
    # "floyd_steinberg" (heavier, can look noisy at 16x16).
    dithering: str = "none"
    # Contrast boost applied before downscaling: "off", "low", "medium"
    # (default, matches this pipeline's original hardcoded boost), "high".
    contrast_boost: str = "medium"
    # Saturation boost applied before downscaling: "off", "low", "medium"
    # (default), "high".
    saturation_boost: str = "medium"
    # Lift brightness on naturally dark source images so they don't render
    # mostly-black on the LEDs. Conservative and capped - see
    # mediainfo/led_image.py.
    dark_image_boost: bool = True
    # When enabled (default), downsample in two stages (LANCZOS to an
    # intermediate size, then nearest-neighbour to the final size) so the
    # result reads as intentional pixel art rather than a blurred photo.
    # When disabled, a single LANCZOS pass produces smoother output.
    pixel_art_mode: bool = True
    # Detect and remove small poster/cover typography (credits, subtitles,
    # track listings) before cropping and downscaling, so it doesn't
    # survive as unreadable noise at 16x16/64x64. Off by default - requires
    # `text_detection_model_path` to point at a locally-provided EAST text-
    # detection model file (not bundled/auto-downloaded). See
    # mediainfo/text_removal.py.
    text_detection_enabled: bool = False
    # Path to a frozen_east_text_detection.pb model file (OpenCV's EAST
    # text detector). Required for text_detection_enabled - if missing or
    # unloadable, the text-removal stage is skipped and a warning is
    # logged, same as if this were left disabled.
    text_detection_model_path: str = ""
    # Remove small/non-essential detected text (credits, subtitles, track
    # listings).
    remove_small_text: bool = True
    # Keep large titles/logos that remain legible at the final LED size
    # instead of removing them like small text.
    preserve_large_logos: bool = True
    # How detected text is actually removed: "inpaint" (best quality,
    # falls back to soft_fill if OpenCV is unavailable at removal time),
    # "soft_fill" (Pillow-only blurred local fill, no extra dependency),
    # or "crop_preference" (don't edit pixels - instead nudge the square
    # crop to avoid the text, when there's slack to do so).
    text_removal_method: str = "inpaint"
    # A detected text region larger than this percentage of the image is
    # treated as too big to be a normal logo ("uncertain") and left alone,
    # rather than being classified as a large logo or removed - see
    # mediainfo/text_removal.py's classify_regions().
    max_logo_area_percent: float = 25.0


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class WebConfig(_OutputFilterMixin):
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8090
    transforms: list = dataclasses.field(default_factory=list)
    # Image-change transition variants to exclude, e.g. [slide-left, zoom].
    # All variants (fade, slide-left, slide-right, slide-up, slide-down,
    # zoom) are used by default, picked at random per image change.
    transition_exclude: list = dataclasses.field(default_factory=list)


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class ThemesConfig(_OutputFilterMixin):
    """A completely separate display from `web` (its own port, its own
    page) that layers selectable, combinable visual effects ("Display
    Themes" - see mediainfo/themes/) on top of the current artwork/
    metadata. Themes enabled at once render simultaneously into one
    combined look, not as alternate single-active skins - see
    mediainfo/outputs/themes.py."""

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8097
    transforms: list = dataclasses.field(default_factory=list)
    # Image-change transition variants to exclude - see WebConfig above.
    transition_exclude: list = dataclasses.field(default_factory=list)
    # One entry per theme, keyed by theme name (e.g. {"glow": {"enabled":
    # true, "intensity": 0.6}}) - deliberately a raw dict, not validated
    # here (mirrors `transforms: list` above): each theme's own config
    # dataclass (mediainfo.config.themes.THEMES_CONFIG_TYPES) validates
    # its own entry via parse_themes(), called from ThemesOutput.__init__.
    themes: dict = dataclasses.field(default_factory=dict)


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class InfoConfig(_OutputFilterMixin):
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8093
    # Image transforms applied before display. Left empty by default so
    # this output shows artwork at its original (high) resolution, unlike
    # outputs aimed at small physical displays.
    transforms: list = dataclasses.field(default_factory=list)
    # Image-change transition variants to exclude - see WebConfig above.
    transition_exclude: list = dataclasses.field(default_factory=list)


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class ConfigUiConfig(_OutputFilterMixin):
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


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class FeedConfig(_OutputFilterMixin):
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8086
    # Feed channel title shown in podcast/RSS apps.
    title: str = "Now Playing"


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class FolderConfig(_OutputFilterMixin):
    enabled: bool = False
    # Directory that mirrors the album art / fanart / posters for whatever
    # is currently playing. Replaced whenever the item changes, and cleared
    # while idle.
    dir: str = "./artwork"
    transforms: list = dataclasses.field(default_factory=list)


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class NestHubConfig(_OutputFilterMixin):
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


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class UlanziConfig(_OutputFilterMixin):
    enabled: bool = False
    # IP address of the Ulanzi TC001 (or other AWTRIX3 device).
    device_ip: str = ""
    # Name of the AWTRIX3 "custom app" used to show now-playing text.
    app_name: str = "now_playing"
    # Optional HTTP basic auth, if configured in AWTRIX3's settings.
    username: str = ""
    password: str = ""
    # Turn the matrix off during this daily window ("HH:MM-HH:MM", wraps
    # midnight, e.g. "23:00-07:00") and back on outside it, via AWTRIX3's
    # /api/power. Empty = always on.
    screen_off_hours: str = ""
    # Daily brightness windows, one "HH:MM-HH:MM=<level>" string per entry
    # (e.g. "08:00-20:00=180", "20:00-08:00=10"). First matching window
    # wins; outside all windows the brightness is left alone. Level is
    # AWTRIX3's native 0-255 range, applied via /api/settings BRI - only
    # effective while AWTRIX3's own auto-brightness (ABRI) is off.
    brightness_schedule: list = dataclasses.field(default_factory=list)


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class MqttConfig(_OutputFilterMixin):
    """Spike: this is the first config dataclass converted from plain
    @dataclasses.dataclass to pydantic's dataclass integration (roadmap
    item 4 - evaluating Pydantic for config validation), kept deliberately
    small in scope. It stays a stdlib-compatible dataclass - dataclasses.
    fields(MqttConfig) still works unchanged, so config_schema.py's schema
    generation and health.py's config_detail_fields() need no changes -
    but construction now raises pydantic.ValidationError (with per-field,
    human-readable messages) instead of a generic TypeError on a bad
    type, an out-of-range value, or an unknown/typo'd key (extra="forbid"
    restores - and improves on - the implicit rejection stdlib dataclasses
    already gave for typo'd keys).
    """

    enabled: bool = False
    # Hostname or IP of the MQTT broker.
    host: str = "localhost"
    port: int = pydantic.Field(default=1883, ge=1, le=65535)
    # Topic to publish now-playing events to.
    topic: str = "mediainfo/now_playing"
    # MQTT client identifier (must be unique per broker connection).
    client_id: str = "mediainfo"
    # Optional broker credentials (leave blank if auth is not configured).
    username: str = ""
    password: str = ""
    # QoS level: 0 = at most once, 1 = at least once, 2 = exactly once.
    qos: int = pydantic.Field(default=0, ge=0, le=2)
    # Retain the last published message so new subscribers immediately see
    # the current state.
    retain: bool = True
    # Publish Home Assistant MQTT discovery messages on every (re)connect,
    # so a "mediainfo" device with now-playing sensors appears in HA
    # automatically - no YAML needed on the HA side. Requires HA's MQTT
    # integration with discovery enabled (its default). Also publishes an
    # availability topic (<topic>/availability) with a last-will, so the
    # entities show "unavailable" in HA when this process goes away.
    ha_discovery: bool = False
    # Topic prefix HA listens on for discovery messages - only change it
    # if your HA instance uses a non-default discovery_prefix.
    ha_discovery_prefix: str = "homeassistant"


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class VideoOutputConfig(_OutputFilterMixin):
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
    "themes": ThemesConfig,
    "ulanzi": UlanziConfig,
    "video": VideoOutputConfig,
    "web": WebConfig,
}
