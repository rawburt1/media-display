"""Builds sources/enrichers/idle sources/outputs from config, and wires
cross-cutting state (the /health provider, the Hitster-safe toggle) onto
the outputs that expose it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from mediainfo import registries
from mediainfo.cache import ImageCache
from mediainfo.config import Config
from mediainfo.health import make_health_provider
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.idle.composite import CompositeIdleWallpaperSource
from mediainfo.musiclibrary import MusicLibrary
from mediainfo.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


def instantiate_outputs(config: Config, config_path: Path, cache: ImageCache) -> list:
    outputs = []
    for name, output_configs in config.outputs.items():
        output_cls = registries.OUTPUT_CLASSES.get(name)
        if output_cls is None:
            logger.warning("Unknown output: %s", name)
            continue
        extra_args = registries.OUTPUT_EXTRA_ARGS.get(name, lambda _config, _path, _cache: ())(
            config, config_path, cache
        )
        for output_config in output_configs:
            if not output_config.enabled:
                continue
            outputs.append(output_cls(output_config, *extra_args))
    return outputs


def build_sources(config: Config) -> list:
    sources = []
    for name in config.priority:
        source_config = config.sources.get(name)
        if source_config is None or not source_config.enabled:
            continue
        source_cls = registries.SOURCE_CLASSES.get(name)
        if source_cls is None:
            logger.warning("Unknown source in priority list: %s", name)
            continue
        sources.append(source_cls(source_config))
    return sources


def build_enrichers(config: Config, library: Optional[MusicLibrary] = None) -> list:
    enrichers = []
    for name, enricher_config in config.enrichers.items():
        if not enricher_config.enabled:
            continue
        enricher_cls = registries.ENRICHER_CLASSES.get(name)
        if enricher_cls is None:
            logger.warning("Unknown enricher: %s", name)
            continue
        if enricher_cls in registries.LIBRARY_AWARE_ENRICHERS:
            enrichers.append(enricher_cls(enricher_config, library))
        else:
            enrichers.append(enricher_cls(enricher_config))
    return enrichers


def build_idle_source(config: Config, library: Optional[MusicLibrary] = None):
    """Build the configured idle wallpaper source(s).

    Multiple sources can be enabled at once - their wallpapers are merged
    into a single pool (see CompositeIdleWallpaperSource), each refetched
    on its own configured rotation_interval_seconds.
    """
    instances: list[IdleWallpaperSource] = []
    for name, idle_config in config.idle.items():
        if not idle_config.enabled:
            continue
        idle_cls = registries.IDLE_CLASSES.get(name)
        if idle_cls is None:
            logger.warning("Unknown idle wallpaper source: %s", name)
            continue
        if idle_cls in registries.LIBRARY_AWARE_IDLE_CLASSES:
            instances.append(idle_cls(idle_config, library))
        else:
            instances.append(idle_cls(idle_config))

    if not instances:
        return None
    if len(instances) == 1:
        return instances[0]
    return CompositeIdleWallpaperSource(instances)


def start_orchestrator(
    config: Config, outputs: list, cache: ImageCache, library: Optional[MusicLibrary] = None
) -> Orchestrator:
    orch = Orchestrator(
        sources=build_sources(config),
        enrichers=build_enrichers(config, library),
        outputs=outputs,
        cache=cache,
        poll_interval_seconds=config.poll_interval_seconds,
        rotation_interval_seconds=config.rotation_interval_seconds,
        idle_source=build_idle_source(config, library),
        backoff_initial_seconds=config.backoff_initial_seconds,
        backoff_max_seconds=config.backoff_max_seconds,
    )
    orch.start()
    return orch


def wire_health_providers(outputs: list, orch: Orchestrator, config: Config) -> None:
    """Register the health provider on every WebOutput and ConfigUiOutput
    instance (the latter uses it for the dashboard UI's status overview -
    see config_dashboard.py)."""
    from mediainfo.outputs.config_ui import ConfigUiOutput
    from mediainfo.outputs.web import WebOutput

    provider = make_health_provider(orch, config, outputs)
    for output in outputs:
        if isinstance(output, (WebOutput, ConfigUiOutput)):
            output.set_health_provider(provider)


def wire_hitster_safe(outputs: list, orch: Orchestrator) -> None:
    """Register the orchestrator's Hitster-safe get/set on every
    ConfigUiOutput instance, so its button can read and toggle it."""
    from mediainfo.outputs.config_ui import ConfigUiOutput

    for output in outputs:
        if isinstance(output, ConfigUiOutput):
            output.set_hitster_safe_handlers(orch.get_hitster_safe, orch.set_hitster_safe)
