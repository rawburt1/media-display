"""Registries mapping config section names to plugin classes.

Classes are referenced by dotted import path here and resolved lazily (on
first use, via `resolve()`) rather than imported eagerly - this module is
imported by most of the app (wiring.py, health.py, config_dashboard.py,
the test suite's registry-completeness checks), so eagerly importing all
~35 plugin modules' own dependencies (Flask, pyatv, paho-mqtt, spotipy,
adb_shell, ...) just to build this file's dicts would be wasted work for
any process that never actually uses most of them.

Adding a new source, output, or enricher starts here (and in
mediainfo/config/, where the matching `*_CONFIG_TYPES` dict lives) -
keep both registries' keys in sync, since a key present in one but not
the other silently produces a "not configured"/"unknown" plugin instead
of an error (see tests/test_registries.py).
"""

from __future__ import annotations

import importlib
from typing import Optional, Union

SOURCE_CLASSES: dict[str, Union[str, type]] = {
    "appletv": "mediainfo.sources.appletv.AppleTvSource",
    "chromecast": "mediainfo.sources.chromecast.ChromecastSource",
    "emby": "mediainfo.sources.jellyfin.EmbySource",
    "homeassistant": "mediainfo.sources.homeassistant.HomeAssistantSource",
    "jellyfin": "mediainfo.sources.jellyfin.JellyfinSource",
    "kodi": "mediainfo.sources.kodi.KodiSource",
    "plex": "mediainfo.sources.plex.PlexSource",
    "ps5": "mediainfo.sources.ps5.Ps5Source",
    "shield": "mediainfo.sources.shield.ShieldSource",
    "sonos": "mediainfo.sources.sonos.SonosSource",
    "spotify": "mediainfo.sources.spotify.SpotifySource",
    "vinyl": "mediainfo.sources.vinyl.VinylSource",
    "youtube": "mediainfo.sources.youtube.YoutubeSource",
}

OUTPUT_CLASSES: dict[str, Union[str, type]] = {
    "config": "mediainfo.outputs.config_ui.ConfigUiOutput",
    "feed": "mediainfo.outputs.feeds.FeedOutput",
    "folder": "mediainfo.outputs.folder.FolderOutput",
    "info": "mediainfo.outputs.info.InfoOutput",
    "mqtt": "mediainfo.outputs.mqtt.MqttOutput",
    "nest_hub": "mediainfo.outputs.nest_hub.NestHubOutput",
    "pixoo": "mediainfo.outputs.pixoo.PixooOutput",
    "ulanzi": "mediainfo.outputs.ulanzi.UlanziOutput",
    "video": "mediainfo.outputs.video.VideoOutput",
    "web": "mediainfo.outputs.web.WebOutput",
}

# Outputs that need extra constructor arguments beyond their own config
# (e.g. ConfigUiOutput needs the path to config.yaml to read/write it; web
# needs the global rotation interval and the ImageCache up front, to drive
# its own per-client rotation before the first on_new_item() call ever
# arrives (e.g. idle wallpapers shown at startup, before anything plays) -
# see WebOutput's docstring for why it can't just reuse the orchestrator's
# rotation like other outputs do). Every Flask-based output also takes
# config.auth, to optionally require HTTP Basic Auth - see web_auth.py.
OUTPUT_EXTRA_ARGS = {
    "config": lambda config, config_path, cache: (config_path, config.auth),
    "web": lambda config, config_path, cache: (
        config.rotation_interval_seconds, cache, config.auth,
    ),
    "info": lambda config, config_path, cache: (config.auth,),
    "feed": lambda config, config_path, cache: (config.auth,),
    "video": lambda config, config_path, cache: (config.auth,),
    "nest_hub": lambda config, config_path, cache: (config.auth,),
}

ENRICHER_CLASSES: dict[str, Union[str, type]] = {
    "discogs": "mediainfo.enrichers.discogs.DiscogsEnricher",
    "fanarttv": "mediainfo.enrichers.fanarttv.FanartTvEnricher",
    "lastfm": "mediainfo.enrichers.lastfm.LastFmEnricher",
    "library": "mediainfo.enrichers.library.LibraryEnricher",
    "lidarr": "mediainfo.enrichers.lidarr.LidarrEnricher",
    "musicbrainz": "mediainfo.enrichers.musicbrainz.MusicBrainzEnricher",
    "omdb": "mediainfo.enrichers.omdb.OmdbEnricher",
    "radarr": "mediainfo.enrichers.radarr.RadarrEnricher",
    "sonarr": "mediainfo.enrichers.sonarr.SonarrEnricher",
    "thetvdb": "mediainfo.enrichers.thetvdb.TheTvDbEnricher",
    "tmdb": "mediainfo.enrichers.tmdb.TmdbEnricher",
    "wikipedia": "mediainfo.enrichers.wikipedia.WikipediaEnricher",
}

IDLE_CLASSES: dict[str, Union[str, type]] = {
    "lastfm": "mediainfo.idle.lastfm.LastFmWallpaperSource",
    "library": "mediainfo.idle.library.LibraryWallpaperSource",
    "local": "mediainfo.idle.local.LocalWallpaperSource",
    "pexels": "mediainfo.idle.pexels.PexelsWallpaperSource",
    "unsplash": "mediainfo.idle.unsplash.UnsplashWallpaperSource",
}

# Idle wallpaper sources that need the local MusicLibrary cache, by
# registry key (not class - keeps the membership check below from forcing
# a resolve()/import of every idle source just to build this set).
LIBRARY_AWARE_IDLE_NAMES = {"library"}

# Enrichers that look up music metadata by artist/album name and so can use
# the local MusicLibrary cache to avoid repeating the same external lookup.
LIBRARY_AWARE_ENRICHER_NAMES = {
    "discogs", "fanarttv", "lastfm", "library", "musicbrainz",
}

# Config attributes to include per output type in the /health response.
OUTPUT_DETAIL_FIELDS: dict = {
    "config":   ["port"],
    "feed":     ["port"],
    "folder":   ["dir"],
    "info":     ["port"],
    "mqtt":     ["host", "port", "topic"],
    "nest_hub": ["device_ip", "server_port"],
    "pixoo":    ["ip"],
    "ulanzi":   ["device_ip"],
    "video":    ["port"],
    "web":      ["port"],
}


def resolve(path: str) -> type:
    """Import and return the class at a dotted path, e.g.
    "mediainfo.sources.kodi.KodiSource"."""
    module_path, _, class_name = path.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _resolve_entry(entry: Union[str, type, None]) -> Optional[type]:
    if entry is None:
        return None
    if isinstance(entry, str):
        return resolve(entry)
    return entry  # already a class - e.g. patched directly in tests


def get_source_class(name: str) -> Optional[type]:
    return _resolve_entry(SOURCE_CLASSES.get(name))


def get_output_class(name: str) -> Optional[type]:
    return _resolve_entry(OUTPUT_CLASSES.get(name))


def get_enricher_class(name: str) -> Optional[type]:
    return _resolve_entry(ENRICHER_CLASSES.get(name))


def get_idle_class(name: str) -> Optional[type]:
    return _resolve_entry(IDLE_CLASSES.get(name))


def _name_for_class(registry: dict, cls: type) -> Optional[str]:
    """Reverse lookup: registry key for an already-imported class, by
    comparing its dotted path against the registry - no import needed,
    since `cls` is already loaded by the time this is called (it's only
    ever used on instantiated, active outputs/enrichers)."""
    path = f"{cls.__module__}.{cls.__qualname__}"
    for name, entry in registry.items():
        if entry == path or entry is cls:
            return name
    return None


def output_name_for_class(cls: type) -> Optional[str]:
    return _name_for_class(OUTPUT_CLASSES, cls)


def enricher_name_for_class(cls: type) -> Optional[str]:
    return _name_for_class(ENRICHER_CLASSES, cls)
