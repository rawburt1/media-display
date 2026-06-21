"""Registries mapping config section names to plugin classes.

Adding a new source, output, or enricher starts here (and in
mediainfo/config.py, where the matching `*_CONFIG_TYPES` dict lives) -
keep both registries' keys in sync, since a key present in one but not
the other silently produces a "not configured"/"unknown" plugin instead
of an error.
"""

from __future__ import annotations

from mediainfo.enrichers.discogs import DiscogsEnricher
from mediainfo.enrichers.fanarttv import FanartTvEnricher
from mediainfo.enrichers.lastfm import LastFmEnricher
from mediainfo.enrichers.library import LibraryEnricher
from mediainfo.enrichers.lidarr import LidarrEnricher
from mediainfo.enrichers.lyrics import LyricsEnricher
from mediainfo.enrichers.musicbrainz import MusicBrainzEnricher
from mediainfo.enrichers.omdb import OmdbEnricher
from mediainfo.enrichers.radarr import RadarrEnricher
from mediainfo.enrichers.sonarr import SonarrEnricher
from mediainfo.enrichers.thetvdb import TheTvDbEnricher
from mediainfo.enrichers.tmdb import TmdbEnricher
from mediainfo.enrichers.wikipedia import WikipediaEnricher
from mediainfo.idle.lastfm import LastFmWallpaperSource
from mediainfo.idle.library import LibraryWallpaperSource
from mediainfo.idle.unsplash import UnsplashWallpaperSource
from mediainfo.outputs.config_ui import ConfigUiOutput
from mediainfo.outputs.feeds import FeedOutput
from mediainfo.outputs.folder import FolderOutput
from mediainfo.outputs.info import InfoOutput
from mediainfo.outputs.mqtt import MqttOutput
from mediainfo.outputs.nest_hub import NestHubOutput
from mediainfo.outputs.pixoo import PixooOutput
from mediainfo.outputs.ulanzi import UlanziOutput
from mediainfo.outputs.video import VideoOutput
from mediainfo.outputs.web import WebOutput
from mediainfo.sources.appletv import AppleTvSource
from mediainfo.sources.chromecast import ChromecastSource
from mediainfo.sources.homeassistant import HomeAssistantSource
from mediainfo.sources.jellyfin import EmbySource, JellyfinSource
from mediainfo.sources.kodi import KodiSource
from mediainfo.sources.plex import PlexSource
from mediainfo.sources.ps5 import Ps5Source
from mediainfo.sources.shield import ShieldSource
from mediainfo.sources.sonos import SonosSource
from mediainfo.sources.spotify import SpotifySource
from mediainfo.sources.vinyl import VinylSource
from mediainfo.sources.youtube import YoutubeSource

SOURCE_CLASSES = {
    "appletv": AppleTvSource,
    "chromecast": ChromecastSource,
    "emby": EmbySource,
    "homeassistant": HomeAssistantSource,
    "jellyfin": JellyfinSource,
    "kodi": KodiSource,
    "plex": PlexSource,
    "ps5": Ps5Source,
    "shield": ShieldSource,
    "sonos": SonosSource,
    "spotify": SpotifySource,
    "vinyl": VinylSource,
    "youtube": YoutubeSource,
}

OUTPUT_CLASSES: dict[str, type] = {
    "config": ConfigUiOutput,
    "feed": FeedOutput,
    "folder": FolderOutput,
    "info": InfoOutput,
    "mqtt": MqttOutput,
    "nest_hub": NestHubOutput,
    "pixoo": PixooOutput,
    "ulanzi": UlanziOutput,
    "video": VideoOutput,
    "web": WebOutput,
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

ENRICHER_CLASSES = {
    "discogs": DiscogsEnricher,
    "fanarttv": FanartTvEnricher,
    "lastfm": LastFmEnricher,
    "library": LibraryEnricher,
    "lidarr": LidarrEnricher,
    "lyrics": LyricsEnricher,
    "musicbrainz": MusicBrainzEnricher,
    "omdb": OmdbEnricher,
    "radarr": RadarrEnricher,
    "sonarr": SonarrEnricher,
    "thetvdb": TheTvDbEnricher,
    "tmdb": TmdbEnricher,
    "wikipedia": WikipediaEnricher,
}

IDLE_CLASSES = {
    "lastfm": LastFmWallpaperSource,
    "library": LibraryWallpaperSource,
    "unsplash": UnsplashWallpaperSource,
}

# Idle wallpaper sources that need the local MusicLibrary cache.
LIBRARY_AWARE_IDLE_CLASSES = {LibraryWallpaperSource}

# Enrichers that look up music metadata by artist/album name and so can use
# the local MusicLibrary cache to avoid repeating the same external lookup.
LIBRARY_AWARE_ENRICHERS = {
    DiscogsEnricher, FanartTvEnricher, LastFmEnricher, LibraryEnricher, LyricsEnricher,
    MusicBrainzEnricher,
}

# Reverse lookups: class → registry key, used when building health data.
OUTPUT_NAME_BY_CLASS = {cls: name for name, cls in OUTPUT_CLASSES.items()}
ENRICHER_NAME_BY_CLASS = {cls: name for name, cls in ENRICHER_CLASSES.items()}

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
