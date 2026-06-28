"""Entry point: python -m mediainfo [--config config.yaml]
              python -m mediainfo auth {appletv,spotify} [--config config.yaml]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from mediainfo.cache import ImageCache
from mediainfo.config import Config, LoggingConfig
from mediainfo.musiclibrary import MusicLibrary
from mediainfo.validation import validate_config
from mediainfo.wiring import (
    build_artwork_overrides,
    instantiate_outputs,
    start_orchestrator,
    wire_artwork_overrides,
    wire_health_providers,
    wire_hitster_safe,
)

logger = logging.getLogger(__name__)

# Config file is polled for changes at this interval (seconds).
_CONFIG_POLL_INTERVAL = 2


def main() -> None:
    # 'auth' and 'import-lidarr' are special subcommands; check for them
    # before the normal parser so the existing `--config` flag keeps
    # working unchanged.
    if len(sys.argv) >= 2 and sys.argv[1] == "auth":
        _auth_main(sys.argv[2:])
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "import-lidarr":
        _import_lidarr_main(sys.argv[2:])
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "validate-config":
        _validate_config_main(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(description="Pixoo64 / web media art display")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    args = parser.parse_args()
    config_path = Path(args.config)

    config = Config.load(config_path)
    _setup_logging(config.logging)
    logger.info("Starting mediainfo")
    validate_config(config)

    cache = ImageCache(
        config.cache.dir,
        max_age_days=config.cache.max_age_days,
        idle_max_age_hours=config.cache.idle_max_age_hours,
        min_width=config.cache.min_width,
        min_height=config.cache.min_height,
    )

    # Outputs are created once and stay alive for the life of the process.
    # Their background servers (Flask, MQTT, etc.) keep running across reloads.
    outputs = instantiate_outputs(config, config_path, cache)

    stop_event = threading.Event()
    stop_handler = _make_stop_handler(stop_event)
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    config_mtime = _file_mtime(config_path)
    library = MusicLibrary(config.library.db_path, max_age_days=config.library.max_age_days)
    overrides = build_artwork_overrides(config)
    orch = start_orchestrator(config, outputs, cache, library, overrides)
    wire_health_providers(outputs, orch, config)
    wire_hitster_safe(outputs, orch)
    wire_artwork_overrides(outputs, overrides)

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
            validate_config(new_config)
            library_config_changed = new_config.library != config.library
            overrides_config_changed = new_config.overrides != config.overrides
            config = new_config

            orch.stop()
            orch.join()
            cache = ImageCache(
                config.cache.dir,
                max_age_days=config.cache.max_age_days,
                idle_max_age_hours=config.cache.idle_max_age_hours,
                min_width=config.cache.min_width,
                min_height=config.cache.min_height,
            )
            if library_config_changed:
                library.close()
                library = MusicLibrary(
                    config.library.db_path, max_age_days=config.library.max_age_days
                )
            if overrides_config_changed:
                overrides = build_artwork_overrides(config)
                wire_artwork_overrides(outputs, overrides)
            orch = start_orchestrator(config, outputs, cache, library, overrides)
            wire_health_providers(outputs, orch, config)
            wire_hitster_safe(outputs, orch)
            logger.info("Config reloaded successfully")
    finally:
        logger.info("Shutting down ...")
        orch.stop()
        orch.join()
        _shutdown_outputs(outputs)
        library.close()
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
    level = logging.getLevelName(log_config.level.upper())
    if not isinstance(level, int):
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


# ---------------------------------------------------------------------------
# validate-config subcommand
# ---------------------------------------------------------------------------

def _validate_config_main(argv: list) -> None:
    """Load and validate config.yaml, printing all warnings as errors.

    Exits 0 if the config is valid, 1 if any warnings are found.
    Designed to be run as a pre-flight check without starting the app:
      python -m mediainfo validate-config --config config/config.yaml
    """
    parser = argparse.ArgumentParser(
        prog="python -m mediainfo validate-config",
        description="Validate a config.yaml file and report any problems",
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    args = parser.parse_args(argv)

    # Capture warnings emitted by Config.load() (unknown plugin names) and
    # validate_config() (blank credentials, missing priority entries, etc.).
    captured: list[logging.LogRecord] = []

    class _CapturingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _CapturingHandler()
    handler.setLevel(logging.WARNING)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)

    try:
        config = Config.load(args.config)
        validate_config(config)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        root.removeHandler(handler)

    if captured:
        for record in captured:
            print(f"WARNING: {record.getMessage()}", file=sys.stderr)
        sys.exit(1)

    print("Config OK")


# ---------------------------------------------------------------------------
# import-lidarr subcommand
# ---------------------------------------------------------------------------

def _import_lidarr_main(argv: list) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m mediainfo import-lidarr",
        description="Populate the local music library from a Lidarr instance",
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    parser.add_argument("--url", required=True, help="Lidarr base URL, e.g. http://192.168.1.122:6003")
    parser.add_argument("--api-key", required=True, help="Lidarr API key")
    args = parser.parse_args(argv)

    from mediainfo.lidarr_import import import_from_lidarr

    config = Config.load(args.config)
    _setup_logging(config.logging)
    library = MusicLibrary(config.library.db_path, max_age_days=config.library.max_age_days)
    try:
        print(f"Importing from Lidarr at {args.url} ...")
        stats = import_from_lidarr(library, args.url, args.api_key)
    finally:
        library.close()

    print(
        f"Done: {stats.artists} artist(s), {stats.albums} album(s), "
        f"{stats.tracks} track(s) imported into {config.library.db_path}"
    )
    if stats.failed_artists:
        print(f"Warning: {stats.failed_artists} artist(s) failed to import (see logs above)")


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
    config = Config.load(config_path)
    atv_cfg = config.sources.get("appletv")
    if atv_cfg is None or not atv_cfg.enabled:
        print(f"Error: Apple TV source is not enabled in {config_path}")
        sys.exit(1)

    asyncio.run(_pair_appletv(atv_cfg.host))


async def _pair_appletv(host: str) -> None:
    import pyatv

    loop = asyncio.get_running_loop()

    print(f"\nScanning for Apple TV at {host} ...")
    results = await pyatv.scan(loop, hosts=[host])
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
            pairing = await pyatv.pair(conf, protocol, loop)
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
                print("\nPairing successful!")
                print("Add to config.yaml under sources.appletv:")
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
