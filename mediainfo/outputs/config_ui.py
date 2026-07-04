"""Config output: a guided web UI for configuring mediainfo without needing
to know YAML - plus an "Advanced" raw-YAML editor for anything the guided
UI doesn't cover.

The page is a single-page app (templates/config_ui/app.html): one Flask-
rendered shell with a sidebar nav and vanilla-JS client-side routing across
nine sections (Overview, Media sources, Displays & outputs, Artwork &
metadata, Idle screen, Automation & schedules, Library & overrides, System
status, Advanced configuration). library.html and overrides.html remain
their own full pages, linked from the shell's "Library & overrides"
section. There is no build step - just the templates as shipped.

The form is generated from the registered source/output/enricher/idle
config dataclasses (mediainfo.config.SOURCE_CONFIG_TYPES etc.), so any
config type added there automatically gets a card - no UI code to update.
Only scalar fields (bool/int/float/str) are editable in the guided UI; list
fields (transforms, blacklist) are left to the "Advanced" raw-YAML editor,
except flat lists of strings (blacklist, speaker_ips, ...) and the
brightness_schedule/screen_off_hours time-window fields, which get their
own small structured widgets client-side (see _field_widget()).

_build_schema() also carries UI-only presentation metadata alongside each
field - friendly label, help text, "essential vs advanced", "required for
this plugin to work", and (for a few known enum-like fields) a fixed list
of choices - so the client never needs to know Python dataclass internals
to render a sensible form. This is presentation only; _scalar_fields()'s
actual value handling is unchanged from before this metadata existed.

Outputs (the only category that supports multiple instances of the same
type, e.g. two `ulanzi` displays) get "+ Add" / duplicate / remove
controls, and an optional cosmetic `label` field (see
_OutputFilterMixin.label in mediainfo/config/outputs.py) so instances can
be told apart by name instead of just "#1"/"#2". Instances can only be
appended or removed from the end - not reordered or removed from the
middle - so that non-form fields like `transforms` on existing instances
stay attached to the right one; saving always overlays posted fields onto
the *existing* instance at each position rather than replacing it
outright, so transforms etc. on instances you don't touch survive.

Saving always validates the result with Config.from_dict() before writing
anything to disk - both the guided form and the Advanced raw editor go
through this same check, so neither can ever write invalid YAML. The
running process's existing config-file hot-reload (see
mediainfo/__main__.py) picks up the change within a couple of seconds - no
restart needed, EXCEPT for `outputs`, which are only instantiated once at
startup and need a restart to pick up added/removed/reconfigured
instances (see _restart_required below).

Secret fields (api_key, password, token, ...) are never sent to the
browser in cleartext: /api/config blanks their value and reports whether
one is currently set via a separate `secrets_set` map, and the client only
ever POSTs a secret field back if the user actually typed a new value -
see the "Configured / Replace" UI in app.html. Leaving a secret field
untouched in the browser is indistinguishable, on the wire, from never
having included that key at all, and the save path already only overlays
whatever keys are present in the POST body - so an untouched secret is
never overwritten.

`self._restart_required` is set whenever a save touches `outputs` (the
one category that can't hot-reload) or `auth` (every Flask-based output's
HTTP Basic Auth check closes over the AuthConfig instance from process
startup - see install_auth() in _build_app() - so a changed password
doesn't take effect until the process actually restarts), and cleared
when /api/restart is called - it's surfaced via /api/overview so the
Overview page can show a "Restart needed" banner. This is a coarse flag
(any outputs/auth save sets it, even a no-op resubmission) rather than a
real diff - simpler, and errs towards nagging rather than missing a real
restart-required change. If you're locked out and can't reach this page
at all, `python -m mediainfo set-password` (see __main__.py) resets
auth.username/auth.password directly in config.yaml from the command
line - same restart caveat applies.

Known cosmetic limitation: when a brand-new instance is appended to an
output type that already has trailing comments after its last existing
instance (e.g. a comment block introducing the next output type), ruamel.yaml
can render the new instance's YAML *before* that comment instead of after
it - visually confusing, but the data itself is unaffected (it still parses
into the same list, in the same order). Re-saving via the "Advanced" raw
editor lets you tidy up the formatting by hand if it bothers you.

This output has write access to config.yaml, including any credentials in
it, with no authentication of its own - see SECURITY.md before exposing it
beyond a trusted local network.

The page also has a "Restart" button, since changes to `outputs` (added/
removed/reconfigured instances) need a process restart to take effect -
unlike sources/enrichers/idle sources, outputs are only instantiated once
at startup (see mediainfo/__main__.py) and aren't recreated by the config
hot-reload. It works by sending SIGTERM to this process - the same signal
SIGTERM/Ctrl-C/`docker stop` already trigger, so it shuts down via the
existing graceful-shutdown path. Whether it actually comes back up depends
on a process supervisor restarting it: the documented `docker-compose.yml`
(restart: unless-stopped) does this automatically; running the process
directly with no supervisor does not - it'll just exit.

The page can also pair an Apple TV (the same pyatv-based flow as
`python -m mediainfo auth appletv`, see __main__.py), without needing
shell/docker-exec access. Apple TV pairing is async (pyatv) and
inherently a multi-step wizard (start -> enter/confirm PIN -> finish), so
it gets its own short-lived background event loop thread per pairing
attempt, created in `_appletv_pair_start` and torn down in
`_appletv_pair_finish`/`_appletv_pair_cancel`. Only one pairing attempt is
tracked at a time, which is fine for a single-operator local admin tool.
"""

from __future__ import annotations

import asyncio
import dataclasses
import io
import logging
import os
import signal
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request, send_file
from ruamel.yaml import YAML

from mediainfo.artwork_overrides import ArtworkOverrideStore
from mediainfo.cache import ImageCache
from mediainfo.config import (
    ENRICHER_CONFIG_TYPES,
    IDLE_CONFIG_TYPES,
    OUTPUT_CONFIG_TYPES,
    SOURCE_CONFIG_TYPES,
    AlertConfig,
    AuthConfig,
    CacheConfig,
    Config,
    ConfigUiConfig,
    HistoryConfig,
    LibraryConfig,
    LoggingConfig,
    OverridesConfig,
    PostersConfig,
)
from mediainfo.config_backup import backup_config_file, list_backups, restore_backup
from mediainfo.models import Artwork, NowPlaying
from mediainfo.musiclibrary import MusicLibrary
from mediainfo.outputs.base import Output
from mediainfo.outputs.config_dashboard import test_enricher, test_output, test_source
from mediainfo.web_auth import install_auth, is_loopback_address

logger = logging.getLogger(__name__)

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
# Displays & outputs, Artwork & metadata) - see _get_hidden_types().
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


_yaml = YAML()
_yaml.preserve_quotes = True

# Give the HTTP response time to reach the browser before this process
# receives SIGTERM and starts shutting down.
_RESTART_DELAY_SECONDS = 0.5


def _restart_process() -> None:
    logger.info("Restarting (SIGTERM to self) - requested via the config UI")
    os.kill(os.getpid(), signal.SIGTERM)


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


@dataclasses.dataclass
class _AppleTvSession:
    """An in-progress pairing attempt, with the resources needed to finish
    or cancel it. The event loop/thread must outlive the request that
    started the pairing, since pyatv's PairingHandler keeps background
    network state tied to the loop it was created on.
    """

    loop: asyncio.AbstractEventLoop
    thread: threading.Thread
    pairing: Any  # pyatv.interface.PairingHandler
    protocol_name: str
    device_name: str
    manual_pin: Optional[int] = None


def _read_config(path: Path) -> Any:
    if not path.exists():
        return _yaml.map()
    with path.open("r", encoding="utf-8") as f:
        return _yaml.load(f) or _yaml.map()


def _dump_config(data: Any) -> str:
    buf = io.StringIO()
    _yaml.dump(data, buf)
    return buf.getvalue()


class ConfigUiOutput(Output):
    handles_images = False

    def __init__(
        self,
        config: ConfigUiConfig,
        config_path: Path,
        auth_config: Optional[AuthConfig] = None,
    ):
        self.config = config
        self.auth_config = auth_config
        self.config_path = Path(config_path)
        self._lock = threading.Lock()
        self._appletv_lock = threading.Lock()
        self._appletv_session: Optional[_AppleTvSession] = None
        self._library: Optional[MusicLibrary] = None
        self._library_db_path: Optional[str] = None
        self._health_fn = None
        self._hitster_safe_get = None
        self._hitster_safe_set = None
        self._overrides: Optional[ArtworkOverrideStore] = None
        # Set whenever a form save touches `outputs` (the one category that
        # needs a restart to take effect, since outputs are only
        # instantiated once at startup) - see the "Restart needed" banner
        # on the Overview page (/api/overview). Cleared when /api/restart
        # is called.
        self._restart_required = False
        self.app = self._build_app()
        threading.Thread(target=self._run_server, daemon=True).start()

    def set_hitster_safe_handlers(self, get_fn, set_fn) -> None:
        """Register the orchestrator's Hitster-safe get/set, so this
        output's button can read and toggle it - see
        Orchestrator.get_hitster_safe."""
        self._hitster_safe_get = get_fn
        self._hitster_safe_set = set_fn

    def set_artwork_overrides(self, store: Optional[ArtworkOverrideStore]) -> None:
        """Register the artwork override store, so the "Overrides" page
        can list/add/remove pins - see wiring.wire_artwork_overrides.
        None means the feature is disabled (overrides.enabled: false)."""
        self._overrides = store

    def set_health_provider(self, fn) -> None:
        """Register a callable that returns the health JSON dict - used by
        the System status section and the Overview page's now-playing/
        active-source summary."""
        self._health_fn = fn

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        pass

    def on_idle(self) -> None:
        pass

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        pass

    def _run_server(self) -> None:
        logger.info("Starting config server on %s:%s", self.config.host, self.config.port)
        self.app.run(host=self.config.host, port=self.config.port, threaded=True)

    # -- request handling -------------------------------------------------

    def _get_library(self) -> MusicLibrary:
        """Lazily open (or reopen, if config.yaml's library.db_path
        changed) a MusicLibrary connection for the library browser.

        Independent of the orchestrator's own MusicLibrary instance -
        this output is created once and outlives config reloads, so it
        manages its own connection rather than holding a reference that
        could be closed out from under it by a reload.
        """
        with self._lock:
            data = _read_config(self.config_path)
        library_cfg = data.get("library") or {}
        db_path = library_cfg.get("db_path", "./library/library.db")
        if self._library is None or self._library_db_path != db_path:
            if self._library is not None:
                self._library.close()
            self._library = MusicLibrary(db_path, max_age_days=library_cfg.get("max_age_days", 30))
            self._library_db_path = db_path
        return self._library

    def _get_values(self):
        """Flat dotted-key values for the single-instance categories
        (general/flat sections/sources/enrichers/idle), plus a parallel
        `secrets_set` map. See _get_output_instances() for the (possibly
        multi-instance) outputs category.

        Secret fields (schema field["secret"]) never carry their real
        value here - the value is always "" and `secrets_set[key]` reports
        whether one is actually configured, so the browser can show
        "Configured" without ever receiving the credential itself.
        """
        with self._lock:
            data = _read_config(self.config_path)

        values: Dict[str, Any] = {}
        secrets_set: Dict[str, bool] = {}
        for name, field_type, default in _GENERAL_FIELDS:
            values[f"general.{name}"] = data.get(name, default)

        for section_name, cls in _FLAT_SECTIONS.items():
            flat_entry = data.get(section_name) or {}
            for field in _scalar_fields(cls, "flat", section_name):
                key = f"{section_name}.{field['name']}"
                raw = flat_entry.get(field["name"], field["default"])
                if field["secret"]:
                    secrets_set[key] = bool(raw)
                    values[key] = ""
                else:
                    values[key] = raw

        for category, registry in _SINGLE_INSTANCE_CATEGORIES.items():
            section = data.get(category) or {}
            for type_name, cls in registry.items():
                entry = section.get(type_name) or {}
                for field in _scalar_fields(cls, category, type_name):
                    key = f"{category}.{type_name}.{field['name']}"
                    raw = entry.get(field["name"], field["default"])
                    if field["secret"]:
                        secrets_set[key] = bool(raw)
                        values[key] = ""
                    else:
                        values[key] = raw
        return values, secrets_set

    def _get_output_instances(self):
        """Return ({output_type: [instance_field_values, ...]}, secrets_set)
        for every registered output type, with at least one (possibly
        all-default) instance per type so the form always has something to
        render.

        Each instance dict includes scalar fields, filter fields, and the
        cosmetic `label` field, so the UI can read/write them all together.
        Secret fields are blanked exactly as in _get_values() - see there
        for why.
        """
        with self._lock:
            data = _read_config(self.config_path)

        section = data.get("outputs") or {}
        result: Dict[str, List[Dict[str, Any]]] = {}
        secrets_set: Dict[str, bool] = {}
        for type_name, cls in OUTPUT_CONFIG_TYPES.items():
            instances = _as_instance_list(section.get(type_name)) or [{}]
            fields = _scalar_fields(cls, "outputs", type_name)
            out_instances = []
            for idx, instance in enumerate(instances):
                entry: Dict[str, Any] = {}
                for f in fields:
                    key = f"outputs.{type_name}.{idx}.{f['name']}"
                    raw = instance.get(f["name"], f["default"])
                    if f["secret"]:
                        secrets_set[key] = bool(raw)
                        entry[f["name"]] = ""
                    else:
                        entry[f["name"]] = raw
                entry.update(_get_filter_values(instance))
                entry[_LABEL_FIELD_NAME] = instance.get(_LABEL_FIELD_NAME, "")
                out_instances.append(entry)
            result[type_name] = out_instances
        return result, secrets_set

    def _get_hidden_types(self) -> Dict[str, List[str]]:
        """Plugin type names hidden from the Media sources/Displays &
        outputs/Artwork & metadata cards - purely a display preference
        (doesn't affect whether a type is enabled/used), stored under the
        `ui_hidden_types` top-level key, which Config doesn't model at all
        (unknown top-level keys are silently ignored by Config.from_dict)
        so this never needs a restart or touches any plugin's behavior.
        """
        with self._lock:
            data = _read_config(self.config_path)
        raw = data.get("ui_hidden_types") or {}
        return {
            category: [n for n in (raw.get(category) or []) if isinstance(n, str)]
            for category in _HIDDEN_TYPE_CATEGORIES
        }

    def _set_hidden_type(self, category: str, name: str, hidden: bool) -> Optional[str]:
        """Add/remove `name` from the hidden-types list for `category`.
        Returns an error message on failure, or None on success.
        """
        with self._lock:
            data = _read_config(self.config_path)
            section = data.setdefault("ui_hidden_types", {})
            names = [n for n in (section.get(category) or []) if isinstance(n, str)]
            if hidden and name not in names:
                names.append(name)
            elif not hidden and name in names:
                names.remove(name)
            if names:
                section[category] = names
            else:
                section.pop(category, None)
            if not section:
                data.pop("ui_hidden_types", None)

            try:
                Config.from_dict(data)
            except Exception as exc:
                logger.warning("Rejected hidden-types update: %s", exc)
                return str(exc)

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            backup_config_file(self.config_path)
            with self.config_path.open("w", encoding="utf-8") as f:
                f.write(_dump_config(data))
        return None

    def _compute_overview(self) -> Dict[str, Any]:
        """Data for the Overview page: health summary, enabled-item counts,
        and the two "needs your attention" flags this output can determine
        by itself (outputs-need-restart, exposed-without-auth) - everything
        else (missing required settings, priority warnings, per-item
        unreachable status) is derived client-side from /api/schema,
        /api/config, and /api/status, which already carry what's needed.
        """
        with self._lock:
            data = _read_config(self.config_path)

        def _count_enabled(category: str, registry: Dict[str, type]) -> int:
            section = data.get(category) or {}
            return sum(
                1 for name in registry
                if isinstance(section.get(name), dict) and section[name].get("enabled")
            )

        def _count_enabled_outputs() -> int:
            section = data.get("outputs") or {}
            count = 0
            for name in OUTPUT_CONFIG_TYPES:
                for instance in _as_instance_list(section.get(name)):
                    if isinstance(instance, dict) and instance.get("enabled"):
                        count += 1
            return count

        counts = {
            "sources_enabled": _count_enabled("sources", SOURCE_CONFIG_TYPES),
            "outputs_enabled": _count_enabled_outputs(),
            "enrichers_enabled": _count_enabled("enrichers", ENRICHER_CONFIG_TYPES),
            "idle_enabled": _count_enabled("idle", IDLE_CONFIG_TYPES),
        }

        now_playing = None
        active_source = None
        if self._health_fn is not None:
            health = self._health_fn()
            now_playing = health.get("now_playing")
            for s in health.get("sources", []):
                if s.get("status") == "active":
                    active_source = s.get("name")
                    break

        return {
            "now_playing": now_playing,
            "active_source": active_source,
            "counts": counts,
            "restart_required": self._restart_required,
            "exposed_without_auth": self._is_exposed_without_auth(),
        }

    def _is_exposed_without_auth(self) -> bool:
        """Whether this instance is bound somewhere reachable beyond this
        machine (host isn't loopback) with no login required - independent
        of any single request's own address (unlike _show_auth_warning,
        which is about whether *this visitor* should see the banner)."""
        auth_on = bool(self.auth_config and self.auth_config.enabled)
        return not is_loopback_address(self.config.host) and self.config.host != "localhost" and not auth_on

    def _save_form(
        self, values: Dict[str, Any], outputs: Dict[str, List[Dict[str, Any]]]
    ) -> Optional[str]:
        """Merge posted form data into config.yaml. Returns an error message
        on failure, or None on success.
        """
        with self._lock:
            data = _read_config(self.config_path)

            self._merge_single_instance_fields(data, values)

            for type_name, instances in outputs.items():
                if type_name not in OUTPUT_CONFIG_TYPES:
                    continue
                self._merge_output_instances(data, type_name, instances)

            # Validate filter fields before any write.
            filter_error = _validate_filter_fields(data)
            if filter_error:
                logger.warning("Rejected config form save (filter): %s", filter_error)
                return filter_error

            # Strip filter fields that are at their no-restriction defaults
            # so existing config files stay tidy.
            _clean_output_filter_defaults(data)

            try:
                Config.from_dict(data)
            except Exception as exc:
                logger.warning("Rejected config form save: %s", exc)
                return str(exc)

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            backup_config_file(self.config_path)
            with self.config_path.open("w", encoding="utf-8") as f:
                f.write(_dump_config(data))

            # `outputs` (added/removed/reconfigured instances) and `auth`
            # both need a restart - outputs are only instantiated once at
            # startup, and every Flask-based output's HTTP Basic Auth
            # check (install_auth(), see _build_app()) closes over the
            # AuthConfig instance passed in at that same startup, which
            # the regular hot-reload never re-wires onto already-running
            # servers. Everything else (sources/enrichers/idle/general/
            # cache/etc.) picks up via hot-reload without a restart.
            if outputs or any(key.startswith("auth.") for key in values):
                self._restart_required = True
        return None

    @staticmethod
    def _merge_single_instance_fields(data: Any, values: Dict[str, Any]) -> None:
        """Write posted "general"/flat-section/single-instance (sources,
        enrichers, idle) field values - keys of the form "general.<field>",
        "<flat_section>.<field>" (e.g. "cache.min_width"), or
        "<category>.<type_name>.<field_name>" - into `data` in place.

        A key simply absent from `values` is left untouched in `data` -
        this is what lets the client omit an unmodified secret field
        entirely and have its existing value survive the save unchanged.
        """
        for key, value in values.items():
            parts = key.split(".")

            if len(parts) == 2 and parts[0] == "general":
                data[parts[1]] = value
                continue

            if len(parts) == 2 and parts[0] in _FLAT_SECTIONS:
                section = data.setdefault(parts[0], {})
                section[parts[1]] = value
                continue

            if len(parts) != 3:
                continue
            category, type_name, field_name = parts
            if (
                category not in _SINGLE_INSTANCE_CATEGORIES
                or type_name not in _SINGLE_INSTANCE_CATEGORIES[category]
            ):
                continue

            section = data.setdefault(category, {})
            entry = section.get(type_name)
            entry = entry if isinstance(entry, dict) else {}
            entry[field_name] = value
            section[type_name] = entry

    @staticmethod
    def _merge_output_instances(
        data: Any, type_name: str, posted_instances: List[Dict[str, Any]]
    ) -> None:
        """Write `posted_instances` (one dict of field values per instance,
        in order) for `type_name` into `data["outputs"]`.

        Existing instances are mutated in place (preserving non-form fields
        like `transforms` and any YAML comments) rather than replaced, for
        every position present in both the existing and posted lists.
        Posted instances beyond the existing count are brand new (plain
        dicts); existing instances beyond the posted count are dropped -
        i.e. instances can only be appended or removed from the end.

        As in _merge_single_instance_fields, a field key absent from a
        posted instance is left untouched on the existing instance - the
        client relies on this to omit untouched secret fields.
        """
        section = data.setdefault("outputs", {})
        existing_instances = _as_instance_list(section.get(type_name))

        merged = []
        for i, posted in enumerate(posted_instances):
            if i < len(existing_instances):
                instance = existing_instances[i]
                for field_name, value in posted.items():
                    instance[field_name] = value
            else:
                instance = dict(posted)
            merged.append(instance)
        section[type_name] = merged

    def _save_raw(self, raw_yaml: str) -> Optional[str]:
        try:
            parsed = _yaml.load(raw_yaml) or {}
            Config.from_dict(parsed)
        except Exception as exc:
            logger.warning("Rejected raw config save: %s", exc)
            return str(exc)

        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            backup_config_file(self.config_path)
            with self.config_path.open("w", encoding="utf-8") as f:
                f.write(raw_yaml)
            # A raw save can change anything, including outputs - safest to
            # assume a restart might be needed rather than silently miss one.
            self._restart_required = True
        return None

    def _restore_backup(self, filename: str) -> Optional[str]:
        """Restore config.yaml from one of its automatic backups (see
        mediainfo.config_backup), resolving `filename` by exact match
        against list_backups() - never as a raw path, since the client
        only ever supplies a name we ourselves listed. Returns an error
        message on failure, or None on success.
        """
        with self._lock:
            backups = list_backups(self.config_path)
            if not backups:
                return "No backups available to restore."
            matches = [b for b in backups if b.name == filename]
            if not matches:
                return f"Unknown backup: {filename!r}."
            restore_backup(self.config_path, matches[0])
            # A restored config.yaml can change anything, including outputs
            # and auth - safest to assume a restart might be needed, same
            # reasoning as _save_raw's raw-YAML save.
            self._restart_required = True
        return None

    # -- Apple TV pairing ---------------------------------------------

    def _appletv_pair_start(self, host: str, protocol_name: str) -> dict:
        with self._appletv_lock:
            if self._appletv_session is not None:
                raise RuntimeError(
                    "A pairing attempt is already in progress - cancel it first."
                )
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, daemon=True)
            thread.start()

        try:
            result = self._run_appletv_async(
                loop, self._do_appletv_pair_start(loop, host, protocol_name)
            )
        except Exception:
            self._stop_appletv_loop(loop, thread)
            raise

        with self._appletv_lock:
            self._appletv_session = _AppleTvSession(
                loop=loop,
                thread=thread,
                pairing=result["pairing"],
                protocol_name=protocol_name,
                device_name=result["device_name"],
                manual_pin=result["manual_pin"],
            )

        return {
            "device_name": result["device_name"],
            "protocol": protocol_name,
            "device_provides_pin": result["device_provides_pin"],
            "manual_pin": result["manual_pin"],
        }

    @staticmethod
    async def _do_appletv_pair_start(loop, host: str, protocol_name: str) -> dict:
        import pyatv

        protocols = {"companion": pyatv.const.Protocol.Companion, "mrp": pyatv.const.Protocol.MRP}
        protocol = protocols.get(protocol_name)
        if protocol is None:
            raise ValueError(f"Unknown protocol: {protocol_name!r} (expected companion or mrp)")

        results = await pyatv.scan(loop, hosts=[host], timeout=5)
        if not results:
            raise RuntimeError(f"No Apple TV found at {host}")
        conf = results[0]

        pairing = await pyatv.pair(conf, protocol, loop)
        await pairing.begin()

        manual_pin = None
        if not pairing.device_provides_pin:
            manual_pin = 1234
            pairing.pin(manual_pin)

        return {
            "pairing": pairing,
            "device_name": conf.name,
            "device_provides_pin": pairing.device_provides_pin,
            "manual_pin": manual_pin,
        }

    def _appletv_pair_finish(self, pin: Optional[str]) -> dict:
        with self._appletv_lock:
            session = self._appletv_session
        if session is None:
            raise RuntimeError('No pairing in progress - click "Start pairing" first.')

        try:
            credentials = self._run_appletv_async(
                session.loop, self._do_appletv_pair_finish(session, pin)
            )
        finally:
            with self._appletv_lock:
                self._appletv_session = None
            self._stop_appletv_loop(session.loop, session.thread)

        field = f"{session.protocol_name}_credentials"
        self._save_appletv_credentials(field, credentials)
        return {"protocol": session.protocol_name, "field": field, "credentials": credentials}

    @staticmethod
    async def _do_appletv_pair_finish(session: _AppleTvSession, pin: Optional[str]) -> str:
        if session.pairing.device_provides_pin:
            if not pin:
                raise ValueError("Enter the PIN shown on the Apple TV.")
            session.pairing.pin(int(pin))

        await session.pairing.finish()

        if not session.pairing.has_paired:
            await session.pairing.close()
            raise RuntimeError("Pairing failed - check the PIN and try again.")

        credentials = session.pairing.service.credentials
        await session.pairing.close()
        return credentials

    def _appletv_pair_cancel(self) -> None:
        with self._appletv_lock:
            session = self._appletv_session
            self._appletv_session = None
        if session is None:
            return
        try:
            self._run_appletv_async(session.loop, session.pairing.close())
        except Exception:
            logger.exception("Error closing cancelled Apple TV pairing session")
        self._stop_appletv_loop(session.loop, session.thread)

    def _save_appletv_credentials(self, field: str, value: str) -> None:
        with self._lock:
            data = _read_config(self.config_path)
            section = data.setdefault("sources", {})
            entry = section.get("appletv")
            entry = entry if isinstance(entry, dict) else {}
            entry[field] = value
            entry["enabled"] = True
            section["appletv"] = entry

            Config.from_dict(data)

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            backup_config_file(self.config_path)
            with self.config_path.open("w", encoding="utf-8") as f:
                f.write(_dump_config(data))

    @staticmethod
    def _run_appletv_async(loop: asyncio.AbstractEventLoop, coro, timeout: float = 30) -> Any:
        """Run `coro` on `loop` (which belongs to a different thread) and
        block this thread until it completes. Split out so tests can
        monkeypatch it to use asyncio.run() instead of a real background
        loop+thread.
        """
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    @staticmethod
    def _stop_appletv_loop(loop: asyncio.AbstractEventLoop, thread: threading.Thread) -> None:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()

    def _show_auth_warning(self) -> bool:
        """Whether the config form should show its auth-warning banner (see
        templates/config_ui/app.html): shown to any non-loopback caller
        when auth is off, because the config form has read+write access to
        config.yaml including all stored credentials.
        """
        if self.auth_config and self.auth_config.enabled:
            return False
        return not is_loopback_address(request.remote_addr)

    def _build_app(self) -> Flask:
        app = Flask(__name__)

        def _shell(initial_section: str):
            return render_template(
                "config_ui/app.html",
                show_auth_warning=self._show_auth_warning(),
                initial_section=initial_section,
            )

        @app.get("/")
        def index():
            return _shell("status" if self.config.ui == "dashboard" else "overview")

        # Both entry points are always reachable on every instance,
        # regardless of `ui` - only the *default* section shown at "/"
        # differs. This lets a dashboard-default instance still reach the
        # editable sections (and vice versa) without running a second
        # output instance. Both render the same single-page shell; only
        # the initially-selected nav section differs.
        @app.get("/form")
        def form_page():
            return _shell("overview")

        @app.get("/dashboard")
        def dashboard_page():
            return _shell("status")

        @app.get("/api/schema")
        def schema():
            return jsonify(_build_schema())

        @app.get("/api/config")
        def get_config():
            with self._lock:
                raw_yaml = (
                    self.config_path.read_text(encoding="utf-8") if self.config_path.exists() else ""
                )
            values, values_secrets = self._get_values()
            outputs, output_secrets = self._get_output_instances()
            return jsonify({
                "values": values,
                "outputs": outputs,
                "raw_yaml": raw_yaml,
                "secrets_set": {**values_secrets, **output_secrets},
                "hidden_types": self._get_hidden_types(),
            })

        @app.get("/api/overview")
        def overview():
            return jsonify(self._compute_overview())

        @app.post("/api/config/form")
        def save_form():
            body = request.get_json(silent=True) or {}
            error = self._save_form(body.get("values") or {}, body.get("outputs") or {})
            if error:
                return jsonify({"ok": False, "error": error}), 400
            return jsonify({"ok": True, "restart_required": self._restart_required})

        @app.post("/api/config/raw")
        def save_raw():
            body = request.get_json(silent=True) or {}
            error = self._save_raw(body.get("yaml") or "")
            if error:
                return jsonify({"ok": False, "error": error}), 400
            return jsonify({"ok": True, "restart_required": self._restart_required})

        @app.post("/api/config/hidden-types")
        def set_hidden_type():
            body = request.get_json(silent=True) or {}
            category = body.get("category")
            name = body.get("name")
            hidden = bool(body.get("hidden"))
            if category not in _HIDDEN_TYPE_CATEGORIES or not isinstance(name, str) or not name:
                return jsonify({"ok": False, "error": "Invalid category or name."}), 400
            error = self._set_hidden_type(category, name, hidden)
            if error:
                return jsonify({"ok": False, "error": error}), 400
            return jsonify({"ok": True, "hidden_types": self._get_hidden_types()})

        @app.get("/api/config/backups")
        def list_config_backups():
            backups = list_backups(self.config_path)
            return jsonify({
                "backups": [{"filename": b.name, "mtime": b.stat().st_mtime} for b in backups]
            })

        @app.post("/api/config/backups/restore")
        def restore_config_backup():
            body = request.get_json(silent=True) or {}
            filename = (body.get("filename") or "").strip()
            if not filename:
                return jsonify({"ok": False, "error": "No backup filename given."}), 400
            error = self._restore_backup(filename)
            if error:
                return jsonify({"ok": False, "error": error}), 400
            response: Dict[str, Any] = {"ok": True, "restart_required": self._restart_required}
            try:
                Config.load(self.config_path)
            except Exception as exc:
                # Backup was valid when captured, but schema/plugins may have
                # moved on since - warn, don't block: this route exists for
                # disaster recovery, and refusing would leave the user stuck.
                response["warning"] = (
                    f"Restored, but the result fails to load ({exc}) - restore a "
                    "different (e.g. older) backup, or fix config.yaml by hand."
                )
            return jsonify(response)

        @app.post("/api/restart")
        def restart():
            self._restart_required = False
            threading.Timer(_RESTART_DELAY_SECONDS, _restart_process).start()
            return jsonify({"ok": True})

        @app.get("/api/hitster-safe")
        def hitster_safe_status():
            enabled = self._hitster_safe_get() if self._hitster_safe_get else False
            return jsonify({"enabled": enabled})

        @app.post("/api/hitster-safe")
        def hitster_safe_toggle():
            if self._hitster_safe_set is None:
                return jsonify({"error": "Hitster-safe is not available"}), 503
            data = request.get_json(silent=True) or {}
            enabled = bool(data.get("enabled"))
            self._hitster_safe_set(enabled)
            return jsonify({"enabled": enabled})

        @app.post("/api/appletv/pair/start")
        def appletv_pair_start():
            body = request.get_json(silent=True) or {}
            host = (body.get("host") or "").strip()
            protocol = (body.get("protocol") or "companion").strip().lower()
            if not host:
                return jsonify({"ok": False, "error": "Enter the Apple TV's host/IP first."}), 400
            try:
                result = self._appletv_pair_start(host, protocol)
            except Exception as exc:
                logger.warning("Apple TV pairing start failed: %s", exc)
                return jsonify({"ok": False, "error": str(exc)}), 400
            return jsonify({"ok": True, **result})

        @app.post("/api/appletv/pair/finish")
        def appletv_pair_finish():
            body = request.get_json(silent=True) or {}
            try:
                result = self._appletv_pair_finish(body.get("pin"))
            except Exception as exc:
                logger.warning("Apple TV pairing finish failed: %s", exc)
                return jsonify({"ok": False, "error": str(exc)}), 400
            return jsonify({"ok": True, **result})

        @app.post("/api/appletv/pair/cancel")
        def appletv_pair_cancel():
            self._appletv_pair_cancel()
            return jsonify({"ok": True})

        @app.get("/library")
        def library_page():
            return render_template("config_ui/library.html")

        @app.get("/api/library/stats")
        def library_stats():
            return jsonify(self._get_library().stats())

        @app.get("/api/library/search")
        def library_search():
            query = (request.args.get("q") or "").strip()
            if not query:
                return jsonify([])
            results = self._get_library().search(query)
            return jsonify([{"id": artist_id, "name": name} for artist_id, name in results])

        @app.get("/api/library/artist/<int:artist_id>")
        def library_artist(artist_id: int):
            library = self._get_library()
            name = library.artist_name(artist_id)
            if name is None:
                return jsonify({"error": "Artist not found"}), 404
            albums = library.albums_for_artist(artist_id)
            tracks = library.tracks_for_artist(artist_id)
            return jsonify({
                "id": artist_id,
                "name": name,
                "mbid": library.get_mbid("artist", artist_id),
                "albums": [{"id": i, "title": t, "mbid": m} for i, t, m in albums],
                "tracks": [{"id": i, "title": t, "mbid": m} for i, t, m in tracks],
            })

        @app.get("/overrides")
        def overrides_page():
            return render_template("config_ui/overrides.html")

        @app.get("/api/overrides")
        def overrides_list():
            if self._overrides is None:
                return jsonify({"enabled": False, "items": []})
            return jsonify({"enabled": True, "items": self._overrides.list()})

        @app.post("/api/overrides")
        def overrides_add():
            if self._overrides is None:
                return jsonify({"ok": False, "error": "Overrides are disabled"}), 503

            title = (request.form.get("title") or "").strip()
            subtitle = (request.form.get("subtitle") or "").strip()
            file = request.files.get("file")
            if not title:
                return jsonify({"ok": False, "error": "Title is required"}), 400
            if file is None or not file.filename:
                return jsonify({"ok": False, "error": "An image file is required"}), 400

            extension = Path(file.filename).suffix or ".jpg"
            self._overrides.set(title, subtitle, file.read(), extension)
            return jsonify({"ok": True})

        @app.delete("/api/overrides")
        def overrides_remove():
            if self._overrides is None:
                return jsonify({"ok": False, "error": "Overrides are disabled"}), 503

            body = request.get_json(silent=True) or {}
            removed = self._overrides.remove(
                (body.get("title") or "").strip(), (body.get("subtitle") or "").strip()
            )
            return jsonify({"ok": removed})

        @app.get("/api/overrides/image/<filename>")
        def overrides_image(filename: str):
            if self._overrides is None:
                return "", 404
            # send_file resolves relative to this safe, fixed directory only
            # - filename never reaches the filesystem as a path (no "..").
            path = self._overrides.dir / Path(filename).name
            if not path.exists():
                return "", 404
            return send_file(path)

        @app.get("/api/status")
        def status():
            if self._health_fn is None:
                return jsonify({"sources": [], "outputs": [], "enrichers": [], "idle_sources": []})
            data = self._health_fn()
            return jsonify({
                "sources": data.get("sources", []),
                "outputs": data.get("outputs", []),
                "enrichers": data.get("enrichers", []),
                "idle_sources": data.get("idle_sources", []),
            })

        @app.post("/api/test/source/<name>")
        def test_source_route(name: str):
            config = Config.load(self.config_path)
            source_config = config.sources.get(name)
            ok, message = test_source(name, source_config)
            return jsonify({"ok": ok, "message": message})

        @app.post("/api/test/enricher/<name>")
        def test_enricher_route(name: str):
            config = Config.load(self.config_path)
            enricher_config = config.enrichers.get(name)
            ok, message = test_enricher(name, enricher_config)
            return jsonify({"ok": ok, "message": message})

        @app.post("/api/test/output")
        def test_output_route():
            body = request.get_json(silent=True) or {}
            type_name = body.get("type", "")
            ok, message = test_output(type_name, body)
            return jsonify({"ok": ok, "message": message})

        install_auth(app, self.auth_config)
        return app
