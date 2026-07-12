"""Builds sources/enrichers/idle sources/outputs from config, and attaches
cross-cutting state (the /health provider, the Hitster-safe toggle, ...) onto
the outputs that expose it - see AppServices (build_app_services()/
attach_services() at the bottom of this module).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from mediainfo import registries
from mediainfo.app_services import AppServices
from mediainfo.artwork_overrides import ArtworkOverrideStore
from mediainfo.cache import ImageCache
from mediainfo.config import Config
from mediainfo.health import make_health_provider
from mediainfo.history import PlaybackHistory
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.idle.composite import CompositeIdleWallpaperSource
from mediainfo.media_data_store import MediaDataStore
from mediainfo.musiclibrary import MusicLibrary
from mediainfo.orchestrator import Orchestrator
from mediainfo.poster_store import PosterStore
from mediainfo.text_cache import TextCache

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


def _enabled_credential(config: Config, name: str, attr: str) -> str:
    """The given attr (e.g. "token"/"api_key") off config.enrichers[name],
    or "" if that enricher section is missing or not enabled - used so
    MediaDataStore can reuse whatever credential a standalone enricher
    already has configured, without requiring a second copy of it."""
    enricher_config = config.enrichers.get(name)
    return getattr(enricher_config, attr) if enricher_config and enricher_config.enabled else ""


def build_mediadata_store(config: Config, cache: ImageCache) -> Optional[MediaDataStore]:
    """Construct the shared MediaDataStore instance used by both
    MediaDataArtworkEnricher and MediaDataLyricsEnricher (see
    registries.MEDIADATA_AWARE_ENRICHER_NAMES /
    MEDIADATA_AWARE_TEXT_ENRICHER_NAMES), or None if neither plugin is
    enabled - so a config that doesn't opt in never even touches disk
    for this feature."""
    artwork_config = config.enrichers.get("mediadata")
    lyrics_config = config.text_enrichers.get("mediadata")
    if not (
        (artwork_config and artwork_config.enabled) or (lyrics_config and lyrics_config.enabled)
    ):
        return None
    return MediaDataStore(
        config.mediadata,
        cache=cache,
        discogs_token=_enabled_credential(config, "discogs", "token"),
        tmdb_api_key=_enabled_credential(config, "tmdb", "api_key"),
        fanarttv_api_key=_enabled_credential(config, "fanarttv", "api_key"),
        lastfm_api_key=_enabled_credential(config, "lastfm", "api_key"),
    )


def build_enrichers(
    config: Config,
    library: Optional[MusicLibrary] = None,
    mediadata_store: Optional[MediaDataStore] = None,
) -> list:
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
        elif name in registries.CACHE_AWARE_ENRICHER_NAMES:
            enrichers.append(enricher_cls(enricher_config, Path(config.cache.dir) / "ai_artwork"))
        elif name in registries.MEDIADATA_AWARE_ENRICHER_NAMES:
            enrichers.append(enricher_cls(enricher_config, mediadata_store))
        else:
            enrichers.append(enricher_cls(enricher_config))
    return enrichers


def build_text_enrichers(config: Config, mediadata_store: Optional[MediaDataStore] = None) -> list:
    """Build the configured text enrichers (lyrics, AI-generated text -
    see mediainfo/enrichers/text_base.py), each sharing one TextCache
    instance under cache.dir/text (same retention as artwork, mirroring
    ImageCache's own idle/music subdirectories) - except "mediadata",
    which reads the shared MediaDataStore instead (see
    registries.MEDIADATA_AWARE_TEXT_ENRICHER_NAMES)."""
    text_cache = TextCache(Path(config.cache.dir) / "text", max_age_days=config.cache.max_age_days)
    text_enrichers = []
    for name, text_enricher_config in config.text_enrichers.items():
        if not text_enricher_config.enabled:
            continue
        text_enricher_cls = registries.get_text_enricher_class(name)
        if text_enricher_cls is None:
            logger.warning("Unknown text enricher: %s", name)
            continue
        if name in registries.MEDIADATA_AWARE_TEXT_ENRICHER_NAMES:
            text_enrichers.append(text_enricher_cls(text_enricher_config, mediadata_store))
        else:
            text_enrichers.append(text_enricher_cls(text_enricher_config, text_cache))
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
    mediadata_store: Optional[MediaDataStore] = None,
) -> Orchestrator:
    # Callers that already need the store themselves (e.g. _start_and_wire,
    # to also put it in the AppServices built for attach_services()) build
    # it once and pass it in here instead of leaving this to build a
    # second, separate instance of it - build_mediadata_store() is called
    # only if one wasn't already supplied, so existing callers that don't
    # care about this are unaffected.
    if mediadata_store is None:
        mediadata_store = build_mediadata_store(config, cache)
    orch = Orchestrator(
        sources=build_sources(config),
        enrichers=build_enrichers(config, library, mediadata_store),
        text_enrichers=build_text_enrichers(config, mediadata_store),
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


def build_app_services(
    orch: Orchestrator,
    config: Config,
    outputs: list,
    history: Optional[PlaybackHistory],
    overrides: Optional[ArtworkOverrideStore],
    mediadata_store: Optional[MediaDataStore],
) -> AppServices:
    """Gather every cross-cutting capability an output might want (health
    reporting, playback history, hitster-safe, artwork refresh/rotate-now,
    the shared MediaDataStore, artwork overrides) into one AppServices,
    handed to every output via attach_services() below.

    Replaces the old one-wire_*()-function-per-capability approach: each
    of those imported the concrete output classes it applied to and
    dispatched with isinstance(), so every new capability meant another
    function, another isinstance check, and another import here. Now
    adding a capability only means adding a field to AppServices plus the
    one output that consumes it in its own attach() override - this
    module no longer needs to know any concrete output type at all.
    """
    return AppServices(
        health_provider=make_health_provider(orch, config, outputs),
        history=history,
        mediadata_store=mediadata_store,
        overrides=overrides,
        get_hitster_safe=orch.get_hitster_safe,
        set_hitster_safe=orch.set_hitster_safe,
        request_artwork_refresh=orch.request_artwork_refresh,
        request_rotation_now=orch.request_rotation_now,
    )


def attach_services(outputs: list, services: AppServices) -> None:
    """Hand every output the current AppServices - each pulls whatever it
    needs via its own Output.attach() override (default: does nothing)."""
    for output in outputs:
        output.attach(services)
