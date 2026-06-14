"""Entry point: python -m pixoo_media [--config config.yaml]"""

from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pixoo_media.cache import ImageCache
from pixoo_media.config import Config
from pixoo_media.enrichers.fanarttv import FanartTvEnricher
from pixoo_media.idle.unsplash import UnsplashWallpaperSource
from pixoo_media.orchestrator import Orchestrator
from pixoo_media.outputs.pixoo import PixooOutput
from pixoo_media.outputs.web import WebOutput
from pixoo_media.sources.kodi import KodiSource
from pixoo_media.sources.sonos import SonosSource

# Registries mapping config names to plugin classes. Adding a new source,
# output, or enricher starts here (and in pixoo_media/config.py).
SOURCE_CLASSES = {
    "kodi": KodiSource,
    "sonos": SonosSource,
}

OUTPUT_CLASSES = {
    "pixoo": PixooOutput,
    "web": WebOutput,
}

ENRICHER_CLASSES = {
    "fanarttv": FanartTvEnricher,
}

IDLE_CLASSES = {
    "unsplash": UnsplashWallpaperSource,
}


def main() -> None:
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

    cache = ImageCache(config.cache.dir)

    outputs = []
    web_output = None
    for name, output_config in config.outputs.items():
        if not output_config.enabled:
            continue
        output_cls = OUTPUT_CLASSES.get(name)
        if output_cls is None:
            logging.warning("Unknown output: %s", name)
            continue
        output = output_cls(output_config)
        outputs.append(output)
        if name == "web":
            web_output = output

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

    if web_output is not None:
        logging.info(
            "Starting web server on %s:%s", web_output.config.host, web_output.config.port
        )
        web_output.run()
    else:
        orchestrator.join()


if __name__ == "__main__":
    main()
