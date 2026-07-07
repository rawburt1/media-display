"""Config dataclasses for `sources.*` plugins."""

from __future__ import annotations

import dataclasses


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
class MopidyConfig:
    enabled: bool = False
    # Mopidy's HTTP host/port - the same one serving its web interface (and
    # the /mopidy/rpc JSON-RPC endpoint this source actually talks to).
    host: str = "localhost"
    port: int = 6680
    # Per-request timeout, in seconds.
    timeout: float = 5.0


@dataclasses.dataclass
class MpdConfig:
    enabled: bool = False
    host: str = "localhost"
    port: int = 6600
    # Leave blank if MPD_PASSWORD (or requirepass) isn't configured.
    password: str = ""
    # Per-request timeout, in seconds.
    timeout: float = 5.0


@dataclasses.dataclass
class LmsConfig:
    enabled: bool = False
    host: str = "localhost"
    port: int = 9000
    # Which player to report on, e.g. "aa:bb:cc:dd:ee:ff" (its MAC address -
    # find it in the LMS web UI under Settings -> Information -> Player
    # Information, or by running the "players" CLI query yourself). Leave
    # blank to auto-select: the first player currently playing, else the
    # first paused, else nothing (idle) - reasonable for a single-player
    # household, but set this explicitly once you have more than one.
    player_id: str = ""
    # Per-request timeout, in seconds.
    timeout: float = 5.0


@dataclasses.dataclass
class SonosConfig:
    enabled: bool = False
    # IP address(es) of Sonos speakers on your network, used as discovery
    # seeds. Any one of them can report the full household topology, so
    # listing more than one (e.g. one per room) keeps every zone visible
    # even if a particular speaker is temporarily off or unreachable.
    speaker_ips: list = dataclasses.field(default_factory=list)
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
class VlcConfig:
    enabled: bool = False
    host: str = "localhost"
    port: int = 8080
    # VLC's Lua HTTP interface password - Tools -> Preferences -> Show
    # settings: All -> Interface -> Main interfaces -> Lua -> Lua HTTP ->
    # Password. The HTTP interface itself must also be enabled under
    # Interface -> Main interfaces -> check "Web".
    password: str = ""
    # Per-request timeout, in seconds.
    timeout: float = 5.0


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
class YoutubeConfig:
    enabled: bool = False
    # IP address of the Android TV device running the YouTube app (e.g.
    # the same Nvidia Shield as `sources.shield` - can point at the same
    # device, since this connects independently over ADB).
    host: str = ""
    port: int = 5555
    # Path to the ADB private key. Generated automatically on first run if
    # missing - accept the resulting authorization prompt on the device's
    # screen. Use a separate key from sources.shield's if pointed at the
    # same device, to avoid two sources racing to (re)create the same file.
    adb_key_path: str = "./adb_keys/youtube"


@dataclasses.dataclass
class ChromecastConfig:
    enabled: bool = False
    # IP addresses of Cast devices to poll (Chromecasts, Google/Android TVs,
    # smart speakers, or any other Cast-compatible receiver) - connected to
    # directly, like sources.sonos's speaker_ips, rather than via zeroconf
    # discovery. Find a device's IP in your router's client list or the
    # Google Home app (device settings -> Wi-Fi).
    device_ips: list = dataclasses.field(default_factory=list)
    # Cast app display names to ignore, e.g. screensaver/backdrop apps that
    # are "playing" something but aren't real now-playing content. Also list
    # any Nest Hub used by outputs.nest_hub here, to avoid it detecting the
    # artwork that output casts to it as something "now playing" (a feedback
    # loop).
    ignore_apps: list = dataclasses.field(
        default_factory=lambda: ["Backdrop", "Default Media Receiver"]
    )


@dataclasses.dataclass
class PlexConfig:
    enabled: bool = False
    host: str = ""
    port: int = 32400
    # See https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/
    token: str = ""


@dataclasses.dataclass
class HomeAssistantConfig:
    enabled: bool = False
    host: str = ""
    port: int = 8123
    use_ssl: bool = False
    # Long-lived access token: your profile (bottom-left in the HA UI) →
    # Security → Long-lived access tokens → Create Token.
    token: str = ""
    # The media_player entity to poll, e.g. "media_player.apple_tv_4k". Find
    # it under Settings → Devices & Services → Entities in the HA UI. Useful
    # for any device HA already tracks but that this codebase otherwise
    # can't read "now playing" from directly (e.g. a tvOS app, such as SVT
    # Play, that doesn't populate Apple's own now-playing API - pyatv (see
    # sources.appletv) can then only ever see it as idle).
    entity_id: str = ""



# Registry mapping config section names to their dataclass types. Adding a
# new source starts here.
SOURCE_CONFIG_TYPES: dict[str, type] = {
    "appletv": AppleTvConfig,
    "chromecast": ChromecastConfig,
    "emby": EmbyConfig,
    "homeassistant": HomeAssistantConfig,
    "jellyfin": JellyfinConfig,
    "kodi": KodiConfig,
    "lms": LmsConfig,
    "mopidy": MopidyConfig,
    "mpd": MpdConfig,
    "plex": PlexConfig,
    "shield": ShieldConfig,
    "sonos": SonosConfig,
    "spotify": SpotifyConfig,
    "vinyl": VinylConfig,
    "vlc": VlcConfig,
    "youtube": YoutubeConfig,
}
