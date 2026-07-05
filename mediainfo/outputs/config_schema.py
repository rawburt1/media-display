"""Form schema generation for the config UI: turns the registered source/
output/enricher/idle config dataclasses into JSON-serializable field
metadata (label, help text, essential/required, widget, choices) that the
client renders into a form - see config_ui.py's module docstring for the
overall design.

Split out of config_ui.py - this module is pure (no Flask, no file I/O,
no ConfigUiOutput state): everything here is either a constant table or a
function of its arguments alone.

Also carries the per-output content-filter helpers (_as_instance_list,
_get_filter_values, _validate_filter_fields, _clean_output_filter_defaults)
since they're part of the same "form data <-> config dataclass" shaping
concern, just for the filter fields specifically (see
_OutputFilterMixin in mediainfo/config/outputs.py) rather than the
per-type scalar fields.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

from mediainfo.config import (
    ENRICHER_CONFIG_TYPES,
    IDLE_CONFIG_TYPES,
    OUTPUT_CONFIG_TYPES,
    SOURCE_CONFIG_TYPES,
    AlertConfig,
    AuthConfig,
    CacheConfig,
    HistoryConfig,
    LibraryConfig,
    LoggingConfig,
    OverridesConfig,
    PostersConfig,
)

_SECRET_HINTS = ("password", "token", "secret", "api_key", "key", "credentials", "pin", "npsso")

# Filter fields live on _OutputFilterMixin (inherited by every output config).
# They are handled by a dedicated UI section instead of the auto-generated
# scalar fields, so we exclude them from _scalar_fields() to avoid duplication.
_FILTER_FIELD_NAMES = frozenset({
    "allow_media_types", "deny_media_types",
    "allow_sources", "deny_sources",
    "idle_when_filtered", "active_hours",
})

_FILTER_DEFAULTS: Dict[str, Any] = {
    "allow_media_types": [],
    "deny_media_types": [],
    "allow_sources": [],
    "deny_sources": [],
    "idle_when_filtered": False,
    "active_hours": "",
}

# Cosmetic per-instance display name (_OutputFilterMixin.label) - handled
# alongside the filter fields (its own bit of UI, not a generic scalar
# field) rather than through _scalar_fields().
_LABEL_FIELD_NAME = "label"

_KNOWN_MEDIA_TYPES = ["music", "movie", "episode", "game"]

# Categories whose type cards can be hidden from view (Media sources,
# Displays & outputs, Artwork & metadata) - see ConfigStore.get_hidden_types().
_HIDDEN_TYPE_CATEGORIES = ("sources", "outputs", "enrichers")

# Categories where each type has exactly one configured instance.
_SINGLE_INSTANCE_CATEGORIES: Dict[str, Dict[str, type]] = {
    "sources": SOURCE_CONFIG_TYPES,
    "enrichers": ENRICHER_CONFIG_TYPES,
    "idle": IDLE_CONFIG_TYPES,
}

_GENERAL_FIELDS = [
    ("poll_interval_seconds", "int", 5),
    ("rotation_interval_seconds", "int", 30),
    # Source priority order, one name per line - see config.example.yaml.
    ("priority", "list", []),
    ("idle_priority", "list", []),
    ("idle_mode", "str", "priority"),
    ("backoff_initial_seconds", "int", 30),
    ("backoff_max_seconds", "int", 300),
    ("nothing_playing_grace_seconds", "float", 2),
]

# Singleton settings sections - like the categories above, but each backed
# by exactly one dataclass (no per-type registry), nested one level under
# their own YAML key (e.g. `cache:`) rather than at the top level like
# `general`'s fields. Keys in the form/values dict look like "cache.dir",
# not "cache.<type_name>.dir".
_FLAT_SECTIONS: Dict[str, type] = {
    "cache": CacheConfig,
    "history": HistoryConfig,
    "library": LibraryConfig,
    "overrides": OverridesConfig,
    # posters.entries (a list of per-show dicts) is excluded by
    # _scalar_fields like `transforms` - raw-YAML only.
    "posters": PostersConfig,
    "alerts": AlertConfig,
    "auth": AuthConfig,
    "logging": LoggingConfig,
}

# Form display titles for _FLAT_SECTIONS, in page order - sent to the page
# as schema["flat_sections"] so adding a section above shows up without
# touching the template.
_FLAT_SECTION_TITLES = [
    ("cache", "Cache"),
    ("history", "Playback History"),
    ("library", "Music Library Cache"),
    ("overrides", "Artwork Overrides"),
    ("posters", "Poster Store"),
    ("alerts", "Alerts"),
    ("auth", "Authentication"),
    ("logging", "Logging"),
]

# List-typed fields simple enough (a flat list of strings) to edit as a
# one-item-per-line text box in the form, rather than the "Advanced" raw
# YAML editor. `transforms` is deliberately excluded - it's a list of
# differently-shaped objects (see config.example.yaml), not a flat list of
# strings, so a generic form field can't represent it usefully.
_SIMPLE_LIST_FIELDS = {
    "speaker_ips", "blacklist", "device_ips", "ignore_apps",
    "transition_exclude", "brightness_schedule",
}

# Fields given a small structured "start-end" time-range widget client-side
# instead of a plain text box, since their format ("HH:MM-HH:MM") is easy
# to get wrong by hand. active_hours is excluded here - it's a filter field
# with its own dedicated UI section (see _FILTER_FIELD_NAMES).
_TIME_RANGE_FIELDS = {"screen_off_hours"}

# ---------------------------------------------------------------------------
# Presentation metadata: friendly labels/descriptions/help text, essential-
# vs-advanced grouping, and known enum choices. All of this is UI sugar
# layered on top of the dataclasses' own fields/comments - it does not
# change what gets validated or saved. Missing entries fall back to a
# humanized field name and no help text, so a newly-added plugin type still
# renders (just without hand-written copy) rather than erroring.
# ---------------------------------------------------------------------------

_CATEGORY_INFO: Dict[str, Dict[str, str]] = {
    "sources": {
        "label": "Media sources",
        "description": (
            "Where mediainfo gets “now playing” information from. Enable the "
            "ones that match your setup, then set their priority order below - "
            "the highest-priority active source wins."
        ),
    },
    "outputs": {
        "label": "Displays & outputs",
        "description": (
            "Where now-playing info actually gets shown or sent - a physical "
            "display, a web page, a smart-home integration, and more. You can "
            "run more than one of the same kind at once."
        ),
    },
    "enrichers": {
        "label": "Artwork & metadata",
        "description": (
            "Optional extra lookups that add better artwork, ratings, or "
            "details on top of what a source already provides. None of "
            "these are required."
        ),
    },
    "idle": {
        "label": "Idle screen",
        "description": "What to show on your displays when nothing is playing.",
    },
}

_TYPE_INFO: Dict[str, Dict[str, Dict[str, str]]] = {
    "sources": {
        "appletv": {"label": "Apple TV", "description": "Detects what's playing on an Apple TV via tvOS's now-playing API. Needs a one-time pairing (below)."},
        "chromecast": {"label": "Chromecast / Google Cast", "description": "Polls Cast-compatible devices (Chromecasts, Google/Android TVs, smart speakers) directly by IP address."},
        "emby": {"label": "Emby", "description": "Reads now-playing sessions from an Emby media server."},
        "homeassistant": {"label": "Home Assistant", "description": "Reads a media_player entity's state from Home Assistant - useful for a device HA already tracks that mediainfo can't read directly."},
        "jellyfin": {"label": "Jellyfin", "description": "Reads now-playing sessions from a Jellyfin media server."},
        "kodi": {"label": "Kodi", "description": "Reads now-playing info from a Kodi media center over its JSON-RPC API."},
        "plex": {"label": "Plex", "description": "Reads now-playing sessions from a Plex Media Server."},
        "ps5": {"label": "PlayStation 5", "description": "Reads what's playing on a PS5 using your PlayStation Network account cookie."},
        "shield": {"label": "Nvidia Shield (Android TV)", "description": "Reads the foreground app on an Android TV device (e.g. Nvidia Shield) over ADB."},
        "sonos": {"label": "Sonos", "description": "Reads what's playing on Sonos speakers on your network."},
        "spotify": {"label": "Spotify", "description": "Reads your current Spotify playback via the Spotify Web API."},
        "vinyl": {"label": "Vinyl recognition", "description": "Identifies vinyl records played through a connected turntable, via the vinyl_recognizer service."},
        "youtube": {"label": "YouTube (Android TV)", "description": "Reads the YouTube app's now-playing state on an Android TV device over ADB."},
    },
    "outputs": {
        "config": {"label": "Configuration UI", "description": "This web page - lets you edit configuration and check status from a browser."},
        "feed": {"label": "RSS/Atom feed", "description": "Publishes now-playing info as an RSS/Atom feed for podcast/feed readers."},
        "folder": {"label": "Folder export", "description": "Mirrors the current artwork/poster into a local folder, for other tools to pick up."},
        "info": {"label": "Info page", "description": "A simple full-screen now-playing info page in a browser."},
        "mqtt": {"label": "MQTT", "description": "Publishes now-playing events to an MQTT broker - handy for a Home Assistant integration."},
        "nest_hub": {"label": "Google Nest Hub", "description": "Casts the current artwork to a Google Nest Hub or other Cast-compatible display."},
        "pixoo": {"label": "Divoom Pixoo", "description": "Sends the current artwork to a Divoom Pixoo LED matrix display."},
        "ulanzi": {"label": "Ulanzi TC001 / AWTRIX3", "description": "Sends now-playing text and graphics to a Ulanzi TC001 or other AWTRIX3 device."},
        "video": {"label": "Video display", "description": "Shows looping idle background video (Pexels/Pixabay) plus now-playing artwork in a browser."},
        "web": {"label": "Web display", "description": "A full-screen now-playing display in any browser, with image transitions."},
    },
    "enrichers": {
        "discogs": {"label": "Discogs", "description": "Looks up album cover art on Discogs."},
        "fanarttv": {"label": "Fanart.tv", "description": "Fetches high-quality movie/TV backdrops and posters."},
        "fingerprint": {"label": "Audio fingerprinting", "description": "Identifies vinyl audio via the vinyl_recognizer service's fingerprint matching."},
        "lastfm": {"label": "Last.fm", "description": "Fetches artist photos from Last.fm."},
        "library": {"label": "Local music library", "description": "Looks up cached metadata from mediainfo's own local music library, avoiding repeat external lookups."},
        "lidarr": {"label": "Lidarr", "description": "Adds a discography list from your Lidarr library."},
        "musicbrainz": {"label": "MusicBrainz", "description": "Looks up album cover art via the free Cover Art Archive - no API key needed."},
        "omdb": {"label": "OMDb", "description": "Adds movie/show ratings from OMDb."},
        "radarr": {"label": "Radarr", "description": "Confirms movie details against your Radarr library."},
        "sonarr": {"label": "Sonarr", "description": "Confirms TV show/episode details against your Sonarr library."},
        "svt": {"label": "SVT Play", "description": "Resolves Swedish SVT Play titles, so other enrichers can find matching artwork."},
        "thetvdb": {"label": "TheTVDB", "description": "Fetches TV show/episode artwork and details."},
        "tmdb": {"label": "TMDB", "description": "Fetches movie/TV artwork and ratings from The Movie Database."},
        "wikipedia": {"label": "Wikipedia", "description": "Adds a short plot or artist summary from Wikipedia - no API key needed."},
    },
    "idle": {
        "lastfm": {"label": "Last.fm scrobble history", "description": "Shows album art from your recent Last.fm listening history while idle."},
        "library": {"label": "Local music library", "description": "Shows album art for random albums from your local music library while idle."},
        "local": {"label": "Local folder", "description": "Shows pictures from a local folder (e.g. your own photos) while idle."},
        "pexels": {"label": "Pexels photos", "description": "Shows photos from Pexels matching your search queries while idle."},
        "unsplash": {"label": "Unsplash photos", "description": "Shows photos from Unsplash matching your search queries while idle."},
    },
}

# Enrichers grouped by purpose for the "Artwork & metadata" page, instead of
# one flat alphabetical list. Every key in ENRICHER_CONFIG_TYPES should
# appear in exactly one group - a group membership test in
# tests/test_config_ui.py catches a new enricher forgetting to be added here.
_ENRICHER_GROUPS: Dict[str, List[str]] = {
    "Movie & TV artwork": ["fanarttv", "thetvdb"],
    "Ratings & summaries": ["tmdb", "omdb", "wikipedia"],
    "Music artwork & artist info": ["musicbrainz", "discogs", "lastfm", "lidarr", "fingerprint"],
    "Local media services": ["library", "sonarr", "radarr", "svt"],
}

# Fields shown "up front" on a card; everything else is collapsed under an
# "Advanced" toggle by default. A generic name-based allowlist rather than a
# per-type list - it covers the common "identity" fields for every plugin
# without needing to hand-curate 40+ types individually.
_ESSENTIAL_FIELD_NAMES = frozenset({
    "enabled", "host", "ip", "device_ip", "device_ips", "server_host", "port",
    "server_port", "api_key", "token", "client_id", "client_secret", "username",
    "password", "npsso", "dir", "speaker_ips", "topic", "entity_id", "queries",
    "size", "adb_key_path", "webhook_url",
    # The Automation & schedules page's core timing knobs - kept visible
    # up front there rather than collapsed, since they're the whole point
    # of that page (backoff_* stays advanced - rarely tuned).
    "poll_interval_seconds", "rotation_interval_seconds", "nothing_playing_grace_seconds",
})

# Fields that must be non-empty for the plugin to actually work, beyond just
# being enabled - drives the Overview page's "missing required settings"
# warning and a "required" hint next to the field itself. Deliberately not
# exhaustive (e.g. sonos/appletv have no strictly-required field here -
# sonos auto-discovers, appletv is filled in by the pairing wizard).
_REQUIRED_FIELDS: Dict[str, Dict[str, frozenset]] = {
    "sources": {
        "chromecast": frozenset({"device_ips"}),
        "emby": frozenset({"host", "api_key"}),
        "homeassistant": frozenset({"host", "token", "entity_id"}),
        "jellyfin": frozenset({"host", "api_key"}),
        "kodi": frozenset({"host"}),
        "plex": frozenset({"host", "token"}),
        "ps5": frozenset({"npsso"}),
        "shield": frozenset({"host"}),
        "spotify": frozenset({"client_id", "client_secret"}),
        "vinyl": frozenset({"host"}),
        "youtube": frozenset({"host"}),
    },
    "outputs": {
        "nest_hub": frozenset({"device_ip", "server_host"}),
        "pixoo": frozenset({"ip"}),
        "ulanzi": frozenset({"device_ip"}),
    },
    "enrichers": {
        "discogs": frozenset({"token"}),
        "fanarttv": frozenset({"api_key"}),
        "lastfm": frozenset({"api_key"}),
        "lidarr": frozenset({"host", "api_key"}),
        "omdb": frozenset({"api_key"}),
        "radarr": frozenset({"host", "api_key"}),
        "sonarr": frozenset({"host", "api_key"}),
        "thetvdb": frozenset({"api_key"}),
        "tmdb": frozenset({"api_key"}),
    },
}

# Known enum-like str fields rendered as a <select> instead of free text.
# Keyed by field name only (not type) - none of these names collide across
# the different dataclasses in mediainfo/config/.
_ENUM_CHOICES: Dict[str, List[str]] = {
    "idle_mode": ["priority", "random"],
    "ui": ["form", "dashboard"],
    "level": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    "source": ["pexels", "pixabay"],
}

# Generic help text shared by fields of the same name across many plugin
# types (host/port/api_key/... mean roughly the same thing everywhere).
_FIELD_HELP: Dict[str, str] = {
    "enabled": "Turn this on to start using it.",
    "host": "The device or server's hostname or IP address on your network.",
    "port": "The network port it listens on - the default is usually correct.",
    "username": "Login username, if this service requires one.",
    "password": "Login password, if this service requires one.",
    "api_key": "A credential from the service's own website or app - see its help text below for where to get one.",
    "token": "An access token from the service's own website or app.",
    "ip": "The device's IP address on your network.",
    "device_ip": "The device's IP address on your network.",
    "device_ips": "One IP address per line.",
    "speaker_ips": "One IP address per line - any single speaker can reveal your whole Sonos household.",
    "queries": "Comma-separated search terms, e.g. \"nature,ocean,mountains\".",
    "topic": "The MQTT topic to publish now-playing events to.",
    "dir": "A folder path on this machine (inside the container, if running under Docker).",
}

# Overrides for specific "<category>.<type>.<field>" combinations, where
# the generic help text above isn't specific enough.
_FIELD_HELP_OVERRIDES: Dict[str, str] = {
    "sources.ps5.npsso": "Long-lived PSN auth cookie. While logged into playstation.com in a browser, visit ca.account.sony.com/api/v1/ssocookie and copy the \"npsso\" value. Expires after about 2 months.",
    "sources.spotify.redirect_uri": "Must exactly match the redirect URI registered in your Spotify developer dashboard app.",
    "sources.homeassistant.entity_id": "The media_player entity to watch, e.g. media_player.apple_tv_4k - find it under Settings → Devices & Services → Entities in Home Assistant.",
    "sources.chromecast.ignore_apps": "Cast app names to ignore (e.g. screensaver apps). Also list any Nest Hub used as an output here, to avoid it detecting its own cast image as \"now playing\".",
    "sources.shield.adb_key_path": "Generated automatically on first run if missing - accept the authorization prompt on the device's screen.",
    "sources.youtube.adb_key_path": "Generated automatically on first run if missing. Use a different key file than sources.shield if pointed at the same device.",
    "outputs.pixoo.size": "64 for the Pixoo64 (most common), 16 for the 16×16 Pixel Art LED Frame.",
    "outputs.pixoo.screen_off_hours": "Turn the panel off during this daily window, e.g. 23:00-07:00. Leave both times empty to always keep it on.",
    "outputs.ulanzi.screen_off_hours": "Turn the display off during this daily window, e.g. 23:00-07:00. Leave both times empty to always keep it on.",
    "outputs.mqtt.ha_discovery": "Automatically add a mediainfo device with now-playing sensors to Home Assistant.",
    "outputs.mqtt.qos": "0 = at most once, 1 = at least once, 2 = exactly once. 0 is fine for most setups.",
    "outputs.video.queries": "Comma-separated search queries; one is picked at random per refresh.",
    "outputs.video.source": "Which stock video provider to pull idle background clips from.",
    "enrichers.thetvdb.pin": "Only needed for \"user-supported\" TheTVDB API keys.",
    "enrichers.lidarr.max_discography_items": "Cap on how many tracks to list for a prolific artist.",
    "idle.local.dir": "Each subfolder here is treated as one destination - one is picked at random each refresh.",
    "idle.local.batch_size": "Number of pictures to pick per refresh, from within the chosen destination.",
}

# Small set of abbreviations that shouldn't be capitalized like a normal
# word when turning a field name into a friendly label.
_ACRONYMS = {
    "ip": "IP", "ips": "IPs", "id": "ID", "url": "URL", "mqtt": "MQTT",
    "qos": "QoS", "ha": "HA", "tv": "TV", "npsso": "NPSSO", "adb": "ADB",
    "rss": "RSS", "ssl": "SSL", "db": "DB", "mbid": "MBID", "api": "API",
}


def _humanize(name: str) -> str:
    """Turn a snake_case field name into a friendly label, e.g.
    "device_ip" -> "Device IP", "api_key" -> "API key"."""
    words = name.split("_")
    out = []
    for i, word in enumerate(words):
        lower = word.lower()
        if lower in _ACRONYMS:
            out.append(_ACRONYMS[lower])
        elif i == 0:
            out.append(word.capitalize())
        else:
            out.append(word)
    return " ".join(out)


def _field_help(category: Optional[str], type_name: Optional[str], field_name: str) -> str:
    if category and type_name:
        override = _FIELD_HELP_OVERRIDES.get(f"{category}.{type_name}.{field_name}")
        if override:
            return override
    return _FIELD_HELP.get(field_name, "")


def _is_required(category: Optional[str], type_name: Optional[str], field_name: str) -> bool:
    if category is None or type_name is None:
        return False
    return field_name in _REQUIRED_FIELDS.get(category, {}).get(type_name, frozenset())


def _field_widget(field_name: str) -> Optional[str]:
    if field_name in _TIME_RANGE_FIELDS:
        return "time_range"
    if field_name == "brightness_schedule":
        return "brightness_schedule"
    return None


def _is_secret(name: str) -> bool:
    lname = name.lower()
    return any(hint in lname for hint in _SECRET_HINTS)


def _scalar_fields(
    cls: type, category: Optional[str] = None, type_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return [{"name", "type", "default", "secret", "label", "help",
    "essential", "required", "widget", "choices"?}] for a config dataclass'
    bool/int/float/str fields, plus any simple flat-list-of-strings field
    named in _SIMPLE_LIST_FIELDS (type "list", rendered as a one-item-per-
    line text box, or a structured widget for brightness_schedule) - other
    list-typed fields (e.g. `transforms`, a list of differently-shaped
    objects) are excluded and only editable via the page's "Advanced" raw
    YAML editor.

    `category`/`type_name` (e.g. "sources"/"kodi") are used to look up
    type-specific help text and required-field metadata - pass None for
    contexts without one (only used today for "general", which has none of
    either).

    Filter fields (_FILTER_FIELD_NAMES) and the cosmetic `label` field are
    also excluded here - they are rendered by their own dedicated bits of
    UI instead (the "Content filters" section and the instance-name input,
    respectively).
    """
    fields = []
    for f in dataclasses.fields(cls):
        if f.name in _FILTER_FIELD_NAMES or f.name == _LABEL_FIELD_NAME:
            continue
        if f.type == "list" and f.name in _SIMPLE_LIST_FIELDS:
            fields.append({
                "name": f.name,
                "type": "list",
                "default": [],
                "secret": False,
                "label": _humanize(f.name),
                "help": _field_help(category, type_name, f.name),
                "essential": f.name in _ESSENTIAL_FIELD_NAMES,
                "required": False,
                "widget": _field_widget(f.name),
            })
            continue
        if f.type not in ("bool", "int", "float", "str"):
            continue
        default = f.default if f.default is not dataclasses.MISSING else ""
        entry: Dict[str, Any] = {
            "name": f.name,
            "type": f.type,
            "default": default,
            "secret": _is_secret(f.name),
            "label": _humanize(f.name),
            "help": _field_help(category, type_name, f.name),
            "essential": f.name in _ESSENTIAL_FIELD_NAMES,
            "required": _is_required(category, type_name, f.name),
            "widget": _field_widget(f.name),
        }
        choices = _ENUM_CHOICES.get(f.name)
        if choices:
            entry["choices"] = choices
        fields.append(entry)
    return fields


def _general_field_schema() -> List[Dict[str, Any]]:
    fields = []
    for name, field_type, default in _GENERAL_FIELDS:
        entry: Dict[str, Any] = {
            "name": name,
            "type": field_type,
            "default": default,
            "secret": False,
            "label": _humanize(name),
            "help": _field_help(None, None, name),
            "essential": name in _ESSENTIAL_FIELD_NAMES,
            "required": False,
            "widget": _field_widget(name),
        }
        choices = _ENUM_CHOICES.get(name)
        if choices:
            entry["choices"] = choices
        fields.append(entry)
    return fields


def _build_schema() -> Dict[str, Any]:
    schema: Dict[str, Any] = {"general": _general_field_schema()}
    for section, cls in _FLAT_SECTIONS.items():
        schema[section] = _scalar_fields(cls, "flat", section)
    for category, registry in _SINGLE_INSTANCE_CATEGORIES.items():
        schema[category] = {name: _scalar_fields(cls, category, name) for name, cls in registry.items()}
    schema["outputs"] = {name: _scalar_fields(cls, "outputs", name) for name, cls in OUTPUT_CONFIG_TYPES.items()}
    schema["filter_meta"] = {
        "media_types": _KNOWN_MEDIA_TYPES,
        "known_sources": sorted(SOURCE_CONFIG_TYPES.keys()),
    }
    schema["flat_sections"] = [
        {"key": key, "title": title} for key, title in _FLAT_SECTION_TITLES
    ]
    schema["type_info"] = _TYPE_INFO
    schema["category_info"] = _CATEGORY_INFO
    schema["enricher_groups"] = _ENRICHER_GROUPS
    return schema


def _as_instance_list(raw: Any) -> list:
    """Outputs may be configured in YAML as a single dict or a list of dicts
    (for multiple instances of the same output type) - normalize to a list.
    """
    if isinstance(raw, list):
        return raw
    return [raw] if raw else []


def _get_filter_values(instance: dict) -> dict:
    result = {}
    for name, default in _FILTER_DEFAULTS.items():
        val = instance.get(name, default)
        if isinstance(default, list):
            result[name] = list(val) if isinstance(val, list) else list(default)
        else:
            result[name] = val if val is not None else default
    return result


def _validate_filter_fields(data: Any) -> Optional[str]:
    from mediainfo.output_filter import validate_active_hours

    outputs = data.get("outputs") or {}
    for type_name, raw in outputs.items():
        for i, inst in enumerate(_as_instance_list(raw)):
            label = f"outputs.{type_name}[{i + 1}]"
            allow_t = set(inst.get("allow_media_types") or [])
            deny_t = set(inst.get("deny_media_types") or [])
            conflict = allow_t & deny_t
            if conflict:
                return f"{label}: media type in both allow and deny: {', '.join(sorted(conflict))}"
            allow_s = set(inst.get("allow_sources") or [])
            deny_s = set(inst.get("deny_sources") or [])
            conflict_s = allow_s & deny_s
            if conflict_s:
                return f"{label}: source in both allow and deny: {', '.join(sorted(conflict_s))}"
            ah = inst.get("active_hours") or ""
            if ah:
                err = validate_active_hours(ah)
                if err:
                    return f"{label}.active_hours: {err}"
    return None


def _clean_output_filter_defaults(data: Any) -> None:
    outputs = data.get("outputs") or {}
    for _type_name, raw in list(outputs.items()):
        for instance in _as_instance_list(raw):
            for name in ("allow_media_types", "deny_media_types", "allow_sources", "deny_sources"):
                if isinstance(instance.get(name), list) and not instance[name]:
                    instance.pop(name, None)
            if instance.get("idle_when_filtered") is False:
                instance.pop("idle_when_filtered", None)
            if not instance.get("active_hours"):
                instance.pop("active_hours", None)
            if not instance.get("label"):
                instance.pop("label", None)
