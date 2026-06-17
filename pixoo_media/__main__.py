"""Entry point: python -m pixoo_media [--config config.yaml]
              python -m pixoo_media auth spotify [--config config.yaml]
"""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pixoo_media.cache import ImageCache
from pixoo_media.config import Config
from pixoo_media.enrichers.fanarttv import FanartTvEnricher
from pixoo_media.enrichers.musicbrainz import MusicBrainzEnricher
from pixoo_media.enrichers.thetvdb import TheTvDbEnricher
from pixoo_media.idle.unsplash import UnsplashWallpaperSource
from pixoo_media.orchestrator import Orchestrator
from pixoo_media.outputs.folder import FolderOutput
from pixoo_media.outputs.nest_hub import NestHubOutput
from pixoo_media.outputs.pixoo import PixooOutput
from pixoo_media.outputs.ulanzi import UlanziOutput
from pixoo_media.outputs.video import VideoOutput
from pixoo_media.outputs.web import WebOutput
from pixoo_media.sources.kodi import KodiSource
from pixoo_media.sources.plex import PlexSource
from pixoo_media.sources.shield import ShieldSource
from pixoo_media.sources.sonos import SonosSource
from pixoo_media.sources.spotify import SpotifySource
from pixoo_media.sources.vinyl import VinylSource

# Registries mapping config names to plugin classes. Adding a new source,
# output, or enricher starts here (and in pixoo_media/config.py).
SOURCE_CLASSES = {
    "kodi": KodiSource,
    "plex": PlexSource,
    "shield": ShieldSource,
    "sonos": SonosSource,
    "spotify": SpotifySource,
    "vinyl": VinylSource,
}

OUTPUT_CLASSES = {
    "pixoo": PixooOutput,
    "web": WebOutput,
    "folder": FolderOutput,
    "nest_hub": NestHubOutput,
    "ulanzi": UlanziOutput,
    "video": VideoOutput,
}

ENRICHER_CLASSES = {
    "fanarttv": FanartTvEnricher,
    "musicbrainz": MusicBrainzEnricher,
    "thetvdb": TheTvDbEnricher,
}

IDLE_CLASSES = {
    "unsplash": UnsplashWallpaperSource,
}


def main() -> None:
    # 'auth' is a special subcommand; check for it before the normal parser so
    # the existing `--config` flag keeps working unchanged.
    if len(sys.argv) >= 2 and sys.argv[1] == "auth":
        _auth_main(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(description="Pixoo64 / web media art display")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    args = parser.parse_args()

    config = Config.load(args.config)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if config.logging.file:
        log_path = Path(config.logging.file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_path,
                maxBytes=config.logging.max_bytes,
                backupCount=config.logging.backup_count,
            )
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )

    sources = []
    for name in config.priority:
        source_config = config.sources.get(name)
        if source_config is None or not source_config.enabled:
            continue
        source_cls = SOURCE_CLASSES.get(name)
        if source_cls is None:
            logging.warning("Unknown source in priority list: %s", name)
            continue
        sources.append(source_cls(source_config))

    cache = ImageCache(config.cache.dir, max_age_days=config.cache.max_age_days)

    outputs = []
    for name, output_configs in config.outputs.items():
        output_cls = OUTPUT_CLASSES.get(name)
        if output_cls is None:
            logging.warning("Unknown output: %s", name)
            continue
        for output_config in output_configs:
            if not output_config.enabled:
                continue
            outputs.append(output_cls(output_config))

    enrichers = []
    for name, enricher_config in config.enrichers.items():
        if not enricher_config.enabled:
            continue
        enricher_cls = ENRICHER_CLASSES.get(name)
        if enricher_cls is None:
            logging.warning("Unknown enricher: %s", name)
            continue
        enrichers.append(enricher_cls(enricher_config))

    idle_source = None
    for name, idle_config in config.idle.items():
        if not idle_config.enabled:
            continue
        idle_cls = IDLE_CLASSES.get(name)
        if idle_cls is None:
            logging.warning("Unknown idle wallpaper source: %s", name)
            continue
        idle_source = idle_cls(idle_config)
        break

    orchestrator = Orchestrator(
        sources=sources,
        enrichers=enrichers,
        outputs=outputs,
        cache=cache,
        poll_interval_seconds=config.poll_interval_seconds,
        rotation_interval_seconds=config.rotation_interval_seconds,
        idle_source=idle_source,
    )
    orchestrator.start()
    orchestrator.join()


def _auth_main(argv: list) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m pixoo_media auth",
        description="Authorize third-party services",
    )
    parser.add_argument("service", choices=["spotify"], help="Service to authorize")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    args = parser.parse_args(argv)

    if args.service == "spotify":
        _auth_spotify(args.config)


def _auth_spotify(config_path: str) -> None:
    from pixoo_media.sources.spotify import SCOPE
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


if __name__ == "__main__":
    main()
