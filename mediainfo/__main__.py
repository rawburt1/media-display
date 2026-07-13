"""Entry point: python -m mediainfo [--config config.yaml]
python -m mediainfo auth {appletv,spotify} [--config config.yaml]
python -m mediainfo set-password [--config config.yaml]
python -m mediainfo restore-backup [--config config.yaml]
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import signal
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from mediainfo.cache import ImageCache
from mediainfo.config import Config, LoggingConfig
from mediainfo.config_backup import backup_config_file, list_backups, restore_backup
from mediainfo.media_data_store import MediaDataStore
from mediainfo.musiclibrary import MusicLibrary
from mediainfo.orchestrator import Orchestrator
from mediainfo.outputs.http_server import SharedHttpServer
from mediainfo.reload_plan import ReloadPlan, compute_reload_plan
from mediainfo.validation import validate_config
from mediainfo.wiring import (
    attach_services,
    build_app_services,
    build_artwork_overrides,
    build_enrichers,
    build_history,
    build_idle_source,
    build_mediadata_store,
    build_poster_store,
    build_sources,
    build_text_enrichers,
    instantiate_outputs,
    start_orchestrator,
)

logger = logging.getLogger(__name__)

_CONFIG_POLL_INTERVAL = 2


class _CapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


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
    if len(sys.argv) >= 2 and sys.argv[1] == "set-password":
        _set_password_main(sys.argv[2:])
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "restore-backup":
        _restore_backup_main(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(description="Pixoo64 / web media art display")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    args = parser.parse_args()
    config_path = Path(args.config)

    config = Config.load(config_path)
    _setup_logging(config.logging)
    logger.info("Starting mediainfo")
    validate_config(config)

    cache = _build_cache(config)

    # One shared HTTP server for every Flask-based output (H1 in
    # docs/architecture-usability-review-2026-07.md) - built once here,
    # same lifetime as `outputs` below (persists across config reloads;
    # only a full restart picks up outputs/http changes - see
    # _warn_output_changes). Each enabled HTTP-flavored output registers
    # its own blueprint during instantiate_outputs(); start() is called
    # once every blueprint is registered, not per-output.
    shared_server = SharedHttpServer(config.http, config.auth)

    # Outputs are created once and stay alive for the life of the process.
    # Their background servers (Flask, MQTT, etc.) keep running across reloads.
    outputs = instantiate_outputs(config, config_path, cache, shared_server)
    shared_server.start()

    stop_event = threading.Event()
    stop_handler = _make_stop_handler(stop_event)
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    config_mtime = _file_mtime(config_path)
    library = MusicLibrary(config.library.db_path, max_age_days=config.library.max_age_days)
    overrides = build_artwork_overrides(config)
    poster_store = build_poster_store(config)
    history = build_history(config)
    state = _start_and_wire(config, outputs, cache, library, overrides, poster_store, history)

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
            # N7 (see docs/architecture-usability-review-2026-07.md): only
            # rebuild the subsystems the plan says actually depend on
            # something that changed - see mediainfo/reload_plan.py. A
            # reload that only touched e.g. history.max_entries no longer
            # reconnects every source or restarts the poll loop.
            plan = compute_reload_plan(config, new_config)
            config = new_config

            if plan.cache_dirty:
                cache = _build_cache(config)
            if plan.library_dirty:
                library.close()
                library = MusicLibrary(
                    config.library.db_path, max_age_days=config.library.max_age_days
                )
            if plan.overrides_dirty:
                overrides = build_artwork_overrides(config)
            if plan.posters_dirty:
                poster_store = build_poster_store(config)
            if plan.history_dirty:
                if history is not None:
                    history.close()
                history = build_history(config)
            state = _start_and_wire(
                config,
                outputs,
                cache,
                library,
                overrides,
                poster_store,
                history,
                previous=state,
                plan=plan,
            )
            logger.info("Config reloaded successfully")
    finally:
        logger.info("Shutting down ...")
        state.orch.stop()
        state.orch.join()
        _shutdown_outputs(outputs)
        shared_server.stop()
        library.close()
        if history is not None:
            history.close()
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


def _build_cache(config: Config) -> ImageCache:
    return ImageCache(
        config.cache.dir,
        max_age_days=config.cache.max_age_days,
        idle_max_age_hours=config.cache.idle_max_age_hours,
        min_width=config.cache.min_width,
        min_height=config.cache.min_height,
    )


@dataclasses.dataclass
class _Subsystems:
    """Everything _start_and_wire() built (or reused) on the most recent
    boot/reload - carried forward as `previous` into the next reload so
    compute_reload_plan()'s ReloadPlan can be honored: whatever it says
    isn't dirty gets handed straight back out instead of rebuilt."""

    orch: Orchestrator
    sources: list
    enrichers: list
    text_enrichers: list
    idle_source: object
    mediadata_store: Optional[MediaDataStore]


def _start_and_wire(
    config: Config,
    outputs: list,
    cache: ImageCache,
    library: MusicLibrary,
    overrides,
    poster_store=None,
    history=None,
    previous: Optional[_Subsystems] = None,
    plan: Optional[ReloadPlan] = None,
) -> _Subsystems:
    """Build (or reuse) the orchestrator's collaborators and (re)start it.

    On first boot (`previous`/`plan` both None) everything is built fresh -
    unchanged from before N7. On a config-file hot-reload, `plan` (see
    mediainfo/reload_plan.py) says which of sources/enrichers/
    text_enrichers/idle_source/mediadata_store actually need rebuilding;
    reusing an already-connected source or already-loaded enricher across
    a reload that didn't touch its config avoids the reconnect/reload
    work, and - more importantly - avoids restarting the orchestrator
    thread at all when nothing it depends on changed (see
    plan.orchestrator_dirty).
    """
    # Built once here (rather than left to start_orchestrator's own
    # internal default) so the same instance can also go into the
    # AppServices built below, instead of each ending up with its own
    # separate MediaDataStore.
    if previous is not None and plan is not None and not plan.mediadata_store_dirty:
        mediadata_store = previous.mediadata_store
    else:
        mediadata_store = build_mediadata_store(config, cache)

    if previous is not None and plan is not None and not plan.sources_dirty:
        sources = previous.sources
    else:
        sources = build_sources(config)

    if previous is not None and plan is not None and not plan.enrichers_dirty:
        enrichers = previous.enrichers
    else:
        enrichers = build_enrichers(config, library, mediadata_store)

    if previous is not None and plan is not None and not plan.text_enrichers_dirty:
        text_enrichers = previous.text_enrichers
    else:
        text_enrichers = build_text_enrichers(config, mediadata_store)

    if previous is not None and plan is not None and not plan.idle_dirty:
        idle_source = previous.idle_source
    else:
        idle_source = build_idle_source(config, library)

    if previous is not None and plan is not None and not plan.orchestrator_dirty:
        orch = previous.orch
    else:
        if previous is not None:
            previous.orch.stop()
            previous.orch.join()
        orch = start_orchestrator(
            config,
            outputs,
            cache,
            library,
            overrides,
            poster_store,
            history,
            mediadata_store,
            sources=sources,
            enrichers=enrichers,
            text_enrichers=text_enrichers,
            idle_source=idle_source,
        )

    services = build_app_services(orch, config, outputs, history, overrides, mediadata_store)
    attach_services(outputs, services)
    return _Subsystems(
        orch=orch,
        sources=sources,
        enrichers=enrichers,
        text_enrichers=text_enrichers,
        idle_source=idle_source,
        mediadata_store=mediadata_store,
    )


def _file_mtime(path: Path) -> Optional[float]:
    """Return the mtime of *path*, or None if the file cannot be stat'd."""
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _warn_output_changes(old: Config, new: Config) -> None:
    """Log a warning if output config changed (outputs are not restarted on
    reload). Output.reload(config) exists for a future version of this
    function to call instead of just warning - not done yet, since
    matching a changed config entry back to the right (possibly
    multi-instance) existing output object isn't solved yet.
    """
    if old.outputs != new.outputs:
        logger.warning(
            "Output configuration changed — restart the service for output changes to take effect"
        )


def _shutdown_outputs(outputs: list) -> None:
    """Tell every output to stop and go idle before the process exits."""
    for output in outputs:
        try:
            output.stop()
        except Exception:
            logger.debug("Output stop() raised during shutdown", exc_info=True)
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

    if handler.records:
        for record in handler.records:
            print(f"WARNING: {record.getMessage()}", file=sys.stderr)
        sys.exit(1)

    print("Config OK")


# ---------------------------------------------------------------------------
# set-password subcommand
# ---------------------------------------------------------------------------


def _set_password_main(argv: list) -> None:
    """Set or reset auth.username/auth.password directly in config.yaml,
    without needing to hand-edit YAML or reach a UI you may be locked out
    of (the config UI's own "Security" card can't help if you've forgotten
    the password it's asking for):
      python -m mediainfo set-password --config config.yaml

    Preserves comments/formatting (ruamel.yaml, like the config UI's own
    save path) and validates the result with Config.from_dict() before
    writing anything - same guarantee as every other way of editing
    config.yaml in this codebase.

    auth.enabled is left untouched unless --enable is passed, so running
    this to merely change an existing password can't accidentally turn
    authentication on for someone who had it off. A restart is required
    for the new credentials to take effect - see the "Restart" button in
    the config UI, or send SIGTERM/`docker compose restart mediainfo` -
    because the running process's already-started servers were wired up
    with the auth config as it was at startup.
    """
    import getpass

    from ruamel.yaml import YAML

    parser = argparse.ArgumentParser(
        prog="python -m mediainfo set-password",
        description="Set or reset the config UI / web outputs' HTTP Basic Auth credentials",
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    parser.add_argument("--username", help="New username (defaults to the existing one, if any)")
    parser.add_argument(
        "--password",
        help="New password (omit to be prompted instead - safer, since a "
        "command-line argument can end up in your shell history)",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Also set auth.enabled: true (by default this command only changes the credentials)",
    )
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    yaml = YAML()
    yaml.preserve_quotes = True
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.load(f) or yaml.map()

    auth = data.setdefault("auth", {})

    username = args.username or auth.get("username") or ""
    if not username:
        username = input("Username: ").strip()
    if not username:
        print("Error: a username is required.", file=sys.stderr)
        sys.exit(1)

    password = args.password
    if not password:
        password = getpass.getpass("New password: ")
        if password != getpass.getpass("Confirm password: "):
            print("Error: passwords did not match.", file=sys.stderr)
            sys.exit(1)
    if not password:
        print("Error: a password is required.", file=sys.stderr)
        sys.exit(1)

    auth["username"] = username
    auth["password"] = password
    if args.enable:
        auth["enabled"] = True

    try:
        Config.from_dict(data)
    except Exception as exc:
        print(f"Error: refusing to save - config would be invalid: {exc}", file=sys.stderr)
        sys.exit(1)

    backup_config_file(config_path)
    with config_path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f)

    print(f"\nPassword set for user '{username}' in {config_path}.")
    if auth.get("enabled"):
        print("Authentication is enabled.")
    else:
        print(
            "Authentication is NOT enabled (auth.enabled is still false) - "
            "this only matters once you turn it on (--enable, the config "
            "UI, or by hand in config.yaml)."
        )
    print(
        "A restart is required for this to take effect - it isn't picked "
        "up by the regular config hot-reload (SIGTERM/Ctrl-C/"
        "`docker compose restart mediainfo`, or the config UI's Restart "
        "button, if you can still reach it)."
    )


# ---------------------------------------------------------------------------
# restore-backup subcommand
# ---------------------------------------------------------------------------


def _restore_backup_main(argv: list) -> None:
    """Restore config.yaml from one of the automatic backups taken before
    every save (config UI, `set-password`, or Apple TV pairing) - see
    mediainfo.config_backup.backup_config_file:
      python -m mediainfo restore-backup --config config.yaml

    With no --backup given, lists the available backups (newest first) and
    prompts for which one to restore. The current config.yaml is itself
    backed up first, so restoring can be undone the same way.
    """
    parser = argparse.ArgumentParser(
        prog="python -m mediainfo restore-backup",
        description="Restore config.yaml from an automatic pre-save backup",
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    parser.add_argument("--list", action="store_true", help="List available backups and exit")
    parser.add_argument(
        "--backup",
        help="Backup filename (as printed by --list) to restore, or 'latest' "
        "for the most recent one - omit to be prompted interactively",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt (for scripting)",
    )
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    backups = list_backups(config_path)
    if not backups:
        print(f"Error: no backups found for {config_path}.", file=sys.stderr)
        sys.exit(1)

    if args.list:
        for backup in backups:
            print(backup.name)
        return

    if args.backup:
        if args.backup == "latest":
            chosen = backups[0]
        else:
            matches = [b for b in backups if b.name == args.backup]
            if not matches:
                print(
                    f"Error: no backup named {args.backup!r} for {config_path} - "
                    "run with --list to see available backups.",
                    file=sys.stderr,
                )
                sys.exit(1)
            chosen = matches[0]
    else:
        print("Available backups (newest first):")
        for i, backup in enumerate(backups, start=1):
            print(f"  {i}. {backup.name}")
        choice = input(f"Restore which one? [1-{len(backups)}]: ").strip()
        try:
            index = int(choice)
            if not (1 <= index <= len(backups)):
                raise ValueError
        except ValueError:
            print("Error: invalid selection.", file=sys.stderr)
            sys.exit(1)
        chosen = backups[index - 1]

    if not args.yes:
        confirm = input(f"Restore {chosen.name} over {config_path}? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted - nothing was changed.")
            return

    restore_backup(config_path, chosen)
    print(
        f"Restored {config_path} from {chosen.name} (the previous contents were themselves backed up first)."
    )

    try:
        Config.load(config_path)
    except Exception as exc:
        print(
            f"Warning: the restored config.yaml fails to load: {exc}\n"
            "Run this command again to restore a different (e.g. older) backup.",
            file=sys.stderr,
        )

    print(
        "Most settings hot-reload within a few seconds; if the restored "
        "config changes `outputs` or `auth`, restart to pick those up "
        "(SIGTERM/Ctrl-C/`docker compose restart mediainfo`, or the config "
        "UI's Restart button)."
    )


# ---------------------------------------------------------------------------
# import-lidarr subcommand
# ---------------------------------------------------------------------------


def _import_lidarr_main(argv: list) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m mediainfo import-lidarr",
        description="Populate the local music library from a Lidarr instance",
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    parser.add_argument(
        "--url", required=True, help="Lidarr base URL, e.g. http://192.168.1.122:6003"
    )
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
