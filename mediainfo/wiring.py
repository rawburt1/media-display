"""Builds sources/enrichers/idle sources/outputs from config, and wires
cross-cutting state (the /health provider, the Hitster-safe toggle) onto
the outputs that expose it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from mediainfo import registries
from mediainfo.artwork_overrides import ArtworkOverrideStore
from mediainfo.cache import ImageCache
from mediainfo.config import Config
from mediainfo.health import make_health_provider
from mediainfo.history import PlaybackHistory
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.idle.composite import CompositeIdleWallpaperSource
from mediainfo.musiclibrary import MusicLibrary
from mediainfo.orchestrator import Orchestrator
from mediainfo.poster_store import PosterStore

logger = logging.getLogger(__name__)


def instantiate_outputs(config: Config, config_path: Path, cache: ImageCache) -> list:
    outputs = []
    for name, output_configs in config.outputs.items():
        output_cls = registries.get_output_class(name)
        if output_cls is None:
            logger.warning("Unknown output: %s", name)
            continue
        extra_args = registries.OUTPUT_EXTRA_ARGS.get(name, lambda _config, _path, _cache: ())(
            config, config_path, cache
        )
        for output_config in output_configs:
            if not output_config.enabled:
                continue
            output = output_cls(output_config, *extra_args)
            output.start()
            outputs.append(output)
    return outputs


def build_sources(config: Config) -> list:
    sources = []
    for name in config.priority:
        source_config = config.sources.get(name)
        if source_config is None or not source_config.enabled:
            continue
        source_cls = registries.get_source_class(name)
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
        enricher_cls = registries.get_enricher_class(name)
        if enricher_cls is None:
            logger.warning("Unknown enricher: %s", name)
            continue
        if name in registries.LIBRARY_AWARE_ENRICHER_NAMES:
            enrichers.append(enricher_cls(enricher_config, library))
        else:
            enrichers.append(enricher_cls(enricher_config))
    return enrichers


def build_text_enrichers(config: Config) -> list:
    """Build the configured text enrichers (lyrics, AI-generated text -
    see mediainfo/enrichers/text_base.py). Always returns [] today since
    no plugin is registered yet (roadmap items 8/9) - kept alongside
    build_enrichers() so those items just add a registry entry."""
    text_enrichers = []
    for name, text_enricher_config in config.text_enrichers.items():
        if not text_enricher_config.enabled:
            continue
        text_enricher_cls = registries.get_text_enricher_class(name)
        if text_enricher_cls is None:
            logger.warning("Unknown text enricher: %s", name)
            continue
        text_enrichers.append(text_enricher_cls(text_enricher_config))
    return text_enrichers


def build_idle_source(config: Config, library: Optional[MusicLibrary] = None):
    """Build the configured idle wallpaper source(s).

    Multiple sources can be enabled at once, but only one ever supplies a
    given batch - they're never mixed together (see
    CompositeIdleWallpaperSource). config.idle_priority controls the order
    they're tried in (any enabled source not listed there is tried last,
    in its config.yaml order); config.idle_mode ("priority", the default,
    or "random") controls whether that order is used as given or
    reshuffled every batch.
    """
    built: dict[str, IdleWallpaperSource] = {}
    for name, idle_config in config.idle.items():
        if not idle_config.enabled:
            continue
        idle_cls = registries.get_idle_class(name)
        if idle_cls is None:
            logger.warning("Unknown idle wallpaper source: %s", name)
            continue
        if name in registries.LIBRARY_AWARE_IDLE_NAMES:
            built[name] = idle_cls(idle_config, library)
        else:
            built[name] = idle_cls(idle_config)

    if not built:
        return None

    ordered_names = [name for name in config.idle_priority if name in built]
    ordered_names += [name for name in built if name not in ordered_names]
    instances = [built[name] for name in ordered_names]

    if len(instances) == 1:
        return instances[0]
    return CompositeIdleWallpaperSource(instances, mode=config.idle_mode)


def build_artwork_overrides(config: Config) -> Optional[ArtworkOverrideStore]:
    if not config.overrides.enabled:
        return None
    return ArtworkOverrideStore(config.overrides.dir)


def build_poster_store(config: Config) -> Optional[PosterStore]:
    if not config.posters.enabled or not config.posters.entries:
        return None
    return PosterStore(config.posters.dir, config.posters.entries)


def build_history(config: Config) -> Optional[PlaybackHistory]:
    if not config.history.enabled:
        return None
    return PlaybackHistory(
        config.history.db_path,
        max_entries=config.history.max_entries,
        dedupe_window_seconds=config.history.dedupe_window_seconds,
    )


def start_orchestrator(
    config: Config,
    outputs: list,
    cache: ImageCache,
    library: Optional[MusicLibrary] = None,
    overrides: Optional[ArtworkOverrideStore] = None,
    poster_store: Optional[PosterStore] = None,
    history: Optional[PlaybackHistory] = None,
) -> Orchestrator:
    orch = Orchestrator(
        sources=build_sources(config),
        enrichers=build_enrichers(config, library),
        text_enrichers=build_text_enrichers(config),
        outputs=outputs,
        cache=cache,
        poll_interval_seconds=config.poll_interval_seconds,
        rotation_interval_seconds=config.rotation_interval_seconds,
        idle_source=build_idle_source(config, library),
        backoff_initial_seconds=config.backoff_initial_seconds,
        backoff_max_seconds=config.backoff_max_seconds,
        nothing_playing_grace_seconds=config.nothing_playing_grace_seconds,
        alert_config=config.alerts,
        overrides=overrides,
        poster_store=poster_store,
        history=history,
    )
    orch.start()
    return orch


def wire_history(outputs: list, history: Optional[PlaybackHistory]) -> None:
    """Register the playback history store on every WebOutput instance,
    so its /history page can list entries and serve their artwork. None
    (history.enabled: false) makes the page report the feature disabled."""
    from mediainfo.outputs.web import WebOutput

    for output in outputs:
        if isinstance(output, WebOutput):
            output.set_history(history)


def wire_health_providers(outputs: list, orch: Orchestrator, config: Config) -> None:
    """Register the health provider on every WebOutput, ConfigUiOutput, and
    MqttOutput instance (the latter publishes it as an HA "problem"
    binary_sensor when ha_discovery is enabled - see config_ui uses it for
    the dashboard UI's status overview, see config_dashboard.py)."""
    from mediainfo.outputs.config_ui import ConfigUiOutput
    from mediainfo.outputs.mqtt import MqttOutput
    from mediainfo.outputs.web import WebOutput

    provider = make_health_provider(orch, config, outputs)
    for output in outputs:
        if isinstance(output, (WebOutput, ConfigUiOutput, MqttOutput)):
            output.set_health_provider(provider)


def wire_hitster_safe(outputs: list, orch: Orchestrator) -> None:
    """Register the orchestrator's Hitster-safe get/set on every
    ConfigUiOutput instance (its own button) and MqttOutput instance (an
    HA "switch" entity, when ha_discovery is enabled)."""
    from mediainfo.outputs.config_ui import ConfigUiOutput
    from mediainfo.outputs.mqtt import MqttOutput

    for output in outputs:
        if isinstance(output, (ConfigUiOutput, MqttOutput)):
            output.set_hitster_safe_handlers(orch.get_hitster_safe, orch.set_hitster_safe)


def wire_artwork_refresh(outputs: list, orch: Orchestrator) -> None:
    """Register Orchestrator.request_artwork_refresh on every MqttOutput
    instance, so an HA "button" entity (when ha_discovery is enabled) can
    trigger it."""
    from mediainfo.outputs.mqtt import MqttOutput

    for output in outputs:
        if isinstance(output, MqttOutput):
            output.set_refresh_artwork_handler(orch.request_artwork_refresh)


def wire_artwork_overrides(outputs: list, overrides: Optional[ArtworkOverrideStore]) -> None:
    """Register the artwork override store on every ConfigUiOutput
    instance, so its "Overrides" page can list/add/remove pins. A no-op
    (the page just reports the feature as disabled) when `overrides` is
    None - see OverridesConfig.enabled."""
    from mediainfo.outputs.config_ui import ConfigUiOutput

    for output in outputs:
        if isinstance(output, ConfigUiOutput):
            output.set_artwork_overrides(overrides)
