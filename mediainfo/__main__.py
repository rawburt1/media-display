"""Entry point: python -m mediainfo [--config config.yaml]
              python -m mediainfo auth {appletv,spotify} [--config config.yaml]
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from mediainfo.cache import ImageCache
from mediainfo.config import Config, LoggingConfig
from mediainfo.orchestrator import Orchestrator
from mediainfo.enrichers.discogs import DiscogsEnricher
from mediainfo.enrichers.fanarttv import FanartTvEnricher
from mediainfo.enrichers.lastfm import LastFmEnricher
from mediainfo.enrichers.musicbrainz import MusicBrainzEnricher
from mediainfo.enrichers.thetvdb import TheTvDbEnricher
from mediainfo.idle.unsplash import UnsplashWallpaperSource
from mediainfo.outputs.feeds import FeedOutput
from mediainfo.outputs.folder import FolderOutput
from mediainfo.outputs.mqtt import MqttOutput
from mediainfo.outputs.nest_hub import NestHubOutput
from mediainfo.outputs.pixoo import PixooOutput
from mediainfo.outputs.ulanzi import UlanziOutput
from mediainfo.outputs.video import VideoOutput
from mediainfo.outputs.web import WebOutput
from mediainfo.sources.appletv import AppleTvSource
from mediainfo.sources.jellyfin import EmbySource, JellyfinSource
from mediainfo.sources.kodi import KodiSource
from mediainfo.sources.plex import PlexSource
from mediainfo.sources.shield import ShieldSource
from mediainfo.sources.sonos import SonosSource
from mediainfo.sources.spotify import SpotifySource
from mediainfo.sources.vinyl import VinylSource

# Registries mapping config names to plugin classes. Adding a new source,
# output, or enricher starts here (and in mediainfo/config.py).
SOURCE_CLASSES = {
    "appletv": AppleTvSource,
    "emby": EmbySource,
    "jellyfin": JellyfinSource,
    "kodi": KodiSource,
    "plex": PlexSource,
    "shield": ShieldSource,
    "sonos": SonosSource,
    "spotify": SpotifySource,
    "vinyl": VinylSource,
}

OUTPUT_CLASSES = {
    "feed": FeedOutput,
    "folder": FolderOutput,
    "mqtt": MqttOutput,
    "nest_hub": NestHubOutput,
    "pixoo": PixooOutput,
    "ulanzi": UlanziOutput,
    "video": VideoOutput,
    "web": WebOutput,
}

ENRICHER_CLASSES = {
    "discogs": DiscogsEnricher,
    "fanarttv": FanartTvEnricher,
    "lastfm": LastFmEnricher,
    "musicbrainz": MusicBrainzEnricher,
    "thetvdb": TheTvDbEnricher,
}

IDLE_CLASSES = {
    "unsplash": UnsplashWallpaperSource,
}

# Reverse lookups: class → registry key, used when building health data.
_OUTPUT_NAME_BY_CLASS = {cls: name for name, cls in OUTPUT_CLASSES.items()}
_ENRICHER_NAME_BY_CLASS = {cls: name for name, cls in ENRICHER_CLASSES.items()}

# Config attributes to include per output type in the /health response.
_OUTPUT_DETAIL_FIELDS: dict = {
    "feed":     ["port"],
    "folder":   ["dir"],
    "mqtt":     ["host", "port", "topic"],
    "nest_hub": ["device_ip", "server_port"],
    "pixoo":    ["ip"],
    "ulanzi":   ["device_ip"],
    "video":    ["port"],
    "web":      ["port"],
}

logger = logging.getLogger(__name__)

# Config file is polled for changes at this interval (seconds).
_CONFIG_POLL_INTERVAL = 2


def main() -> None:
    # 'auth' is a special subcommand; check for it before the normal parser so
    # the existing `--config` flag keeps working unchanged.
    if len(sys.argv) >= 2 and sys.argv[1] == "auth":
        _auth_main(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(description="Pixoo64 / web media art display")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    args = parser.parse_args()
    config_path = Path(args.config)

    config = Config.load(config_path)
    _setup_logging(config.logging)
    logger.info("Starting mediainfo")

    # Outputs are created once and stay alive for the life of the process.
    # Their background servers (Flask, MQTT, etc.) keep running across reloads.
    outputs = _instantiate_outputs(config)

    stop_event = threading.Event()
    stop_handler = _make_stop_handler(stop_event)
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    config_mtime = _file_mtime(config_path)
    cache = ImageCache(config.cache.dir, max_age_days=config.cache.max_age_days)
    orch = _start_orchestrator(config, outputs, cache)
    _wire_health_providers(outputs, orch, config)

    try:
        # Main loop: sleep until a stop signal or a config-file change.
        # stop_event.wait(timeout) returns True as soon as the event is set.
        while not stop_event.wait(timeout=_CONFIG_POLL_INTERVAL):
            mtime = _file_mtime(config_path)
            if mtime is None or mtime == config_mtime:
                continue

            config_mtime = mtime
            logger.info("Config file changed; reloading ...")
            try:
                new_config = Config.load(config_path)
            except Exception:
                logger.exception("Config reload failed; keeping current configuration")
                continue

            _warn_output_changes(config, new_config)
            config = new_config

            orch.stop()
            orch.join()
            cache = ImageCache(config.cache.dir, max_age_days=config.cache.max_age_days)
            orch = _start_orchestrator(config, outputs, cache)
            _wire_health_providers(outputs, orch, config)
            logger.info("Config reloaded successfully")
    finally:
        logger.info("Shutting down ...")
        orch.stop()
        orch.join()
        _shutdown_outputs(outputs)
        logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

def _make_stop_handler(stop_event: threading.Event):
    """Return a SIGTERM/SIGINT handler that sets *stop_event*."""
    def _handler(sig, frame):
        logger.info("Received %s; shutting down gracefully", signal.Signals(sig).name)
        stop_event.set()
    return _handler


# ---------------------------------------------------------------------------
# Lifecycle utilities
# ---------------------------------------------------------------------------

def _file_mtime(path: Path) -> Optional[float]:
    """Return the mtime of *path*, or None if the file cannot be stat'd."""
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _warn_output_changes(old: Config, new: Config) -> None:
    """Log a warning if output config changed (outputs are not restarted on reload)."""
    if old.outputs != new.outputs:
        logger.warning(
            "Output configuration changed — restart the service for output changes to take effect"
        )


def _shutdown_outputs(outputs: list) -> None:
    """Tell every output to go idle before the process exits."""
    for output in outputs:
        try:
            output.on_idle()
        except Exception:
            logger.debug("Output on_idle() raised during shutdown", exc_info=True)


def _setup_logging(log_config: LoggingConfig) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_config.file:
        log_path = Path(log_config.file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_path,
                maxBytes=log_config.max_bytes,
                backupCount=log_config.backup_count,
            )
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# Plugin instantiation
# ---------------------------------------------------------------------------

def _instantiate_outputs(config: Config) -> list:
    outputs = []
    for name, output_configs in config.outputs.items():
        output_cls = OUTPUT_CLASSES.get(name)
        if output_cls is None:
            logger.warning("Unknown output: %s", name)
            continue
        for output_config in output_configs:
            if not output_config.enabled:
                continue
            outputs.append(output_cls(output_config))
    return outputs


def _build_sources(config: Config) -> list:
    sources = []
    for name in config.priority:
        source_config = config.sources.get(name)
        if source_config is None or not source_config.enabled:
            continue
        source_cls = SOURCE_CLASSES.get(name)
        if source_cls is None:
            logger.warning("Unknown source in priority list: %s", name)
            continue
        sources.append(source_cls(source_config))
    return sources


def _build_enrichers(config: Config) -> list:
    enrichers = []
    for name, enricher_config in config.enrichers.items():
        if not enricher_config.enabled:
            continue
        enricher_cls = ENRICHER_CLASSES.get(name)
        if enricher_cls is None:
            logger.warning("Unknown enricher: %s", name)
            continue
        enrichers.append(enricher_cls(enricher_config))
    return enrichers


def _build_idle_source(config: Config):
    for name, idle_config in config.idle.items():
        if not idle_config.enabled:
            continue
        idle_cls = IDLE_CLASSES.get(name)
        if idle_cls is None:
            logger.warning("Unknown idle wallpaper source: %s", name)
            continue
        return idle_cls(idle_config)
    return None


def _start_orchestrator(config: Config, outputs: list, cache: ImageCache) -> Orchestrator:
    orch = Orchestrator(
        sources=_build_sources(config),
        enrichers=_build_enrichers(config),
        outputs=outputs,
        cache=cache,
        poll_interval_seconds=config.poll_interval_seconds,
        rotation_interval_seconds=config.rotation_interval_seconds,
        idle_source=_build_idle_source(config),
    )
    orch.start()
    return orch


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

def _make_health_provider(orch: Orchestrator, config: Config, outputs: list):
    """Return a callable that builds the full /health JSON dict."""

    def _health() -> dict:
        data = orch.get_health()
        active_source = data["active_source"]
        polled_ago = data["source_last_polled_ago"]
        output_errors = data["output_errors"]

        # Sources — active/idle for those in the orchestrator; disabled /
        # not_configured for everything else in the registry.
        active_source_names = {s.name for s in orch.sources}
        sources = []
        for source in orch.sources:
            entry: dict = {
                "name": source.name,
                "status": "active" if source.name == active_source else "idle",
            }
            if source.name in polled_ago:
                entry["last_polled_ago_seconds"] = polled_ago[source.name]
            sources.append(entry)
        for name in SOURCE_CLASSES:
            if name in active_source_names:
                continue
            src_cfg = config.sources.get(name)
            if src_cfg is not None:
                sources.append({"name": name, "status": "disabled"})
            else:
                sources.append({"name": name, "status": "not_configured"})

        # Outputs
        active_output_types: set = set()
        output_list = []
        for i, output in enumerate(outputs):
            cls = type(output)
            type_name = _OUTPUT_NAME_BY_CLASS.get(cls, cls.__name__)
            active_output_types.add(type_name)
            err = output_errors.get(i)
            entry = {"type": type_name, "status": "error" if err else "ok"}
            if err:
                entry["last_error"] = err["message"]
                entry["last_error_ago_seconds"] = err["ago_seconds"]
            cfg = getattr(output, "config", None)
            if cfg:
                for field in _OUTPUT_DETAIL_FIELDS.get(type_name, []):
                    val = getattr(cfg, field, None)
                    if val not in (None, ""):
                        entry[field] = val
            output_list.append(entry)
        for type_name in OUTPUT_CLASSES:
            if type_name in active_output_types:
                continue
            if config.outputs.get(type_name):
                output_list.append({"type": type_name, "status": "disabled"})
            else:
                output_list.append({"type": type_name, "status": "not_configured"})

        # Enrichers
        active_enricher_names: set = set()
        enrichers = []
        for enricher in orch.enrichers:
            name = _ENRICHER_NAME_BY_CLASS.get(type(enricher), type(enricher).__name__)
            active_enricher_names.add(name)
            enrichers.append({"name": name, "status": "ok"})
        for name in ENRICHER_CLASSES:
            if name in active_enricher_names:
                continue
            enc_cfg = config.enrichers.get(name)
            if enc_cfg is not None:
                enrichers.append({"name": name, "status": "disabled"})
            else:
                enrichers.append({"name": name, "status": "not_configured"})

        # Idle sources — list of all known idle sources with their status.
        idle_sources = []

        # Traditional wallpaper idle sources (IDLE_CLASSES registry).
        active_idle_name: Optional[str] = None
        if orch.idle_source:
            active_idle_name = (
                type(orch.idle_source).__name__.removesuffix("WallpaperSource").lower()
            )
            idle_sources.append({
                "type": active_idle_name,
                "status": "ok",
                "wallpapers_loaded": data["idle_wallpapers_loaded"],
            })
        for name in IDLE_CLASSES:
            if name == active_idle_name:
                continue
            idle_cfg = config.idle.get(name)
            if idle_cfg is not None:
                status = "disabled" if not idle_cfg.enabled else "ok"
            else:
                status = "not_configured"
            idle_sources.append({"type": name, "status": status})

        # Video outputs expose their own idle video source (pexels/pixabay).
        from mediainfo.outputs.video import VideoOutput
        for output in outputs:
            if isinstance(output, VideoOutput):
                idle_sources.append(output.idle_health_entry())

        return {
            "status": "ok",
            "uptime_seconds": data["uptime_seconds"],
            "poll_interval_seconds": data["poll_interval_seconds"],
            "rotation_interval_seconds": data["rotation_interval_seconds"],
            "now_playing": data["now_playing"],
            "sources": sources,
            "outputs": output_list,
            "enrichers": enrichers,
            "idle_sources": idle_sources,
        }

    return _health


def _wire_health_providers(outputs: list, orch: Orchestrator, config: Config) -> None:
    """Register the health provider on every WebOutput instance."""
    from mediainfo.outputs.web import WebOutput

    provider = _make_health_provider(orch, config, outputs)
    for output in outputs:
        if isinstance(output, WebOutput):
            output.set_health_provider(provider)


# ---------------------------------------------------------------------------
# Auth subcommand
# ---------------------------------------------------------------------------

def _auth_main(argv: list) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m mediainfo auth",
        description="Authorize third-party services",
    )
    parser.add_argument("service", choices=["appletv", "spotify"], help="Service to authorize")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    args = parser.parse_args(argv)

    if args.service == "appletv":
        _auth_appletv(args.config)
    elif args.service == "spotify":
        _auth_spotify(args.config)


def _auth_spotify(config_path: str) -> None:
    from mediainfo.sources.spotify import SCOPE
    from spotipy.oauth2 import SpotifyOAuth

    config = Config.load(config_path)
    spotify_cfg = config.sources.get("spotify")
    if spotify_cfg is None or not spotify_cfg.enabled:
        print(f"Error: Spotify source is not enabled in {config_path}")
        sys.exit(1)

    Path(spotify_cfg.cache_path).parent.mkdir(parents=True, exist_ok=True)

    auth = SpotifyOAuth(
        client_id=spotify_cfg.client_id,
        client_secret=spotify_cfg.client_secret,
        redirect_uri=spotify_cfg.redirect_uri,
        scope=SCOPE,
        cache_path=spotify_cfg.cache_path,
        open_browser=False,
    )

    print("\nOpen this URL in your browser:\n")
    print(" ", auth.get_authorize_url())
    print("\nAfter authorizing, you will be redirected to a URL that looks like:")
    print(f"  {spotify_cfg.redirect_uri}?code=...")
    redirect_url = input("\nPaste the full redirect URL here: ").strip()
    code = auth.parse_response_code(redirect_url)
    token_info = auth.get_access_token(code, as_dict=True, check_cache=False)

    if token_info:
        print(f"\nAuthorization successful! Token cached at: {spotify_cfg.cache_path}")
    else:
        print("\nAuthorization failed — check your client_id, client_secret, and redirect_uri.")
        sys.exit(1)


def _auth_appletv(config_path: str) -> None:
    import asyncio
    import pyatv

    config = Config.load(config_path)
    atv_cfg = config.sources.get("appletv")
    if atv_cfg is None or not atv_cfg.enabled:
        print(f"Error: Apple TV source is not enabled in {config_path}")
        sys.exit(1)

    asyncio.run(_pair_appletv(atv_cfg.host))


async def _pair_appletv(host: str) -> None:
    import pyatv

    print(f"\nScanning for Apple TV at {host} ...")
    results = await pyatv.scan(hosts=[host])
    if not results:
        print(f"Error: No Apple TV found at {host}")
        sys.exit(1)

    conf = results[0]
    print(f"Found: {conf.name}\n")

    # Companion is the recommended protocol for tvOS 15+; fall back to MRP.
    protocols_to_try = [pyatv.Protocol.Companion, pyatv.Protocol.MRP]
    for protocol in protocols_to_try:
        proto_name = protocol.name.lower()
        print(f"Pairing with {protocol.name} protocol ...")
        try:
            pairing = await pyatv.pair(conf, protocol=protocol)
            await pairing.begin()

            if pairing.device_provides_pin:
                raw = input(f"Enter the PIN shown on {conf.name}: ").strip()
                pairing.pin(int(raw))
            else:
                pin = 1234
                pairing.pin(pin)
                input(f"Enter {pin} on your Apple TV, then press Enter here: ")

            await pairing.finish()

            if pairing.has_paired:
                creds = pairing.service.credentials
                print(f"\nPairing successful!")
                print(f"Add to config.yaml under sources.appletv:")
                print(f"  {proto_name}_credentials: {creds}")
                await pairing.close()
                return

            print(f"  {protocol.name} pairing failed; trying next protocol ...")
            await pairing.close()
        except Exception as exc:
            print(f"  {protocol.name} not supported: {exc}")

    print("\nCould not pair with any supported protocol.")
    print("Ensure the Apple TV is on the same network and Developer Mode is not required.")
    sys.exit(1)


if __name__ == "__main__":
    main()
