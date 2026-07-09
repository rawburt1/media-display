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
    "browser": "mediainfo.sources.browser.BrowserSource",
    "chromecast": "mediainfo.sources.chromecast.ChromecastSource",
    "emby": "mediainfo.sources.jellyfin.EmbySource",
    "foobar2000": "mediainfo.sources.foobar2000.Foobar2000Source",
    "homeassistant": "mediainfo.sources.homeassistant.HomeAssistantSource",
    "jellyfin": "mediainfo.sources.jellyfin.JellyfinSource",
    "kodi": "mediainfo.sources.kodi.KodiSource",
    "lms": "mediainfo.sources.lms.LmsSource",
    "mopidy": "mediainfo.sources.mopidy.MopidySource",
    "mpd": "mediainfo.sources.mpd.MpdSource",
    "plex": "mediainfo.sources.plex.PlexSource",
    "shield": "mediainfo.sources.shield.ShieldSource",
    "sonos": "mediainfo.sources.sonos.SonosSource",
    "spotify": "mediainfo.sources.spotify.SpotifySource",
    "vinyl": "mediainfo.sources.vinyl.VinylSource",
    "vlc": "mediainfo.sources.vlc.VlcSource",
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
    "themes": "mediainfo.outputs.themes.ThemesOutput",
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
    # Pixoo disk-caches its LED-prepared derivative via the shared
    # ImageCache (see mediainfo/led_image.py + ImageCache.get_derived_path)
    # instead of reprocessing the image on every update().
    "pixoo": lambda config, config_path, cache: (cache,),
    # Themes get the shared ImageCache the same way every other output
    # does - via on_new_item(now_playing, cache), not the constructor
    # (mirrors info/web's own image-path resolution: the orchestrator
    # already resolves/transforms the image before update() is called;
    # a theme's own per-item ImageCache.get_derived_path() bakes happen
    # in on_new_item(), which already receives cache as an argument).
    "themes": lambda config, config_path, cache: (config.auth,),
}

# Display Theme plugins (see mediainfo/themes/base.py) hosted by the
# `themes` output (mediainfo/outputs/themes.py). Configured via
# mediainfo.config.themes.THEMES_CONFIG_TYPES, not one of the *_CONFIG_TYPES
# dicts below, since a theme isn't its own output/enricher - it's nested
# inside one `themes` output instance's own `themes:` config.
THEME_CLASSES: dict[str, Union[str, type]] = {
    "blurred_background": "mediainfo.themes.blurred_background.BlurredBackgroundTheme",
    "color_palette": "mediainfo.themes.color_palette.ColorPaletteTheme",
    "equalizer": "mediainfo.themes.equalizer.EqualizerTheme",
    "glow": "mediainfo.themes.glow.GlowTheme",
    "ken_burns": "mediainfo.themes.ken_burns.KenBurnsTheme",
    "media_mosaic": "mediainfo.themes.media_mosaic.MediaMosaicTheme",
    "timeline": "mediainfo.themes.timeline.TimelineTheme",
    "vinyl": "mediainfo.themes.vinyl.VinylTheme",
    "word_cloud": "mediainfo.themes.word_cloud.WordCloudTheme",
}

ENRICHER_CLASSES: dict[str, Union[str, type]] = {
    "ai_artwork": "mediainfo.enrichers.ai_artwork.AiArtworkEnricher",
    "discogs": "mediainfo.enrichers.discogs.DiscogsEnricher",
    "fanarttv": "mediainfo.enrichers.fanarttv.FanartTvEnricher",
    "fingerprint": "mediainfo.enrichers.fingerprint.FingerprintEnricher",
    "lastfm": "mediainfo.enrichers.lastfm.LastFmEnricher",
    "library": "mediainfo.enrichers.library.LibraryEnricher",
    "lidarr": "mediainfo.enrichers.lidarr.LidarrEnricher",
    "mediadata": "mediainfo.enrichers.mediadata.MediaDataArtworkEnricher",
    "musicbrainz": "mediainfo.enrichers.musicbrainz.MusicBrainzEnricher",
    "omdb": "mediainfo.enrichers.omdb.OmdbEnricher",
    "radarr": "mediainfo.enrichers.radarr.RadarrEnricher",
    "sonarr": "mediainfo.enrichers.sonarr.SonarrEnricher",
    "svt": "mediainfo.enrichers.svt.SvtEnricher",
    "thetvdb": "mediainfo.enrichers.thetvdb.TheTvDbEnricher",
    "tmdb": "mediainfo.enrichers.tmdb.TmdbEnricher",
    "wikipedia": "mediainfo.enrichers.wikipedia.WikipediaEnricher",
}

# Foundation for roadmap items 8/9 (lyrics / AI-generated text enrichers,
# see mediainfo/enrichers/text_base.py). Adding another plugin means one
# entry here (dotted class path) plus its config dataclass in
# mediainfo.config.TEXT_ENRICHER_CONFIG_TYPES.
TEXT_ENRICHER_CLASSES: dict[str, Union[str, type]] = {
    "lrclib": "mediainfo.enrichers.lrclib.LrclibEnricher",
    "mediadata": "mediainfo.enrichers.mediadata_lyrics.MediaDataLyricsEnricher",
    "ollama_text": "mediainfo.enrichers.ollama_text.OllamaTextEnricher",
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

# Enrichers that need a local directory to cache generated (rather than
# downloaded) content into, by registry key - see wiring.build_enrichers().
CACHE_AWARE_ENRICHER_NAMES = {"ai_artwork"}

# Artwork/text enrichers that read the unified MediaDataStore cache (see
# mediainfo/media_data_store.py), by registry key - wiring.py constructs one
# shared MediaDataStore instance and injects it into whichever of these are
# enabled instead of the CACHE_AWARE_ENRICHER_NAMES TextCache/ImageCache path.
MEDIADATA_AWARE_ENRICHER_NAMES = {"mediadata"}
MEDIADATA_AWARE_TEXT_ENRICHER_NAMES = {"mediadata"}

# Config attributes to include per output type in the /health response.
OUTPUT_DETAIL_FIELDS: dict = {
    "config":   ["label", "port"],
    "feed":     ["label", "port"],
    "folder":   ["label", "dir"],
    "info":     ["label", "port"],
    "mqtt":     ["label", "host", "port", "topic"],
    "nest_hub": ["label", "device_ip", "server_port"],
    "pixoo":    ["label", "ip"],
    "themes":   ["label", "port"],
    "ulanzi":   ["label", "device_ip"],
    "video":    ["label", "port"],
    "web":      ["label", "port"],
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


def get_text_enricher_class(name: str) -> Optional[type]:
    return _resolve_entry(TEXT_ENRICHER_CLASSES.get(name))


def get_idle_class(name: str) -> Optional[type]:
    return _resolve_entry(IDLE_CLASSES.get(name))


def get_theme_class(name: str) -> Optional[type]:
    return _resolve_entry(THEME_CLASSES.get(name))


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
