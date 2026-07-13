"""Builds sources/enrichers/idle sources/outputs from config, and attaches
cross-cutting state (the /health provider, the Hitster-safe toggle, ...) onto
the outputs that expose it - see AppServices (build_app_services()/
attach_services() at the bottom of this module).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

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
from mediainfo.outputs.base import Output
from mediainfo.outputs.http_server import SharedHttpServer
from mediainfo.poster_store import PosterStore
from mediainfo.text_cache import TextCache

logger = logging.getLogger(__name__)


def _compute_url_mount(name: str, index: int, count: int, output_cls: type, label: str) -> tuple:
    """Return (url_prefix, blueprint_name) for one output instance -
    H1 in docs/architecture-usability-review-2026-07.md.

    Base prefix is "/<name>" ("" for the one declared root_mounted, e.g.
    web - see Output.root_mounted). The first instance of a type uses the
    base prefix unmounted; every instance after that needs its own
    `label` (_OutputFilterMixin.label - existing field, previously
    cosmetic only) to be told apart, since they'd otherwise collide on
    the same URL - raises a clear error rather than silently colliding or
    crashing deep inside Flask's own blueprint registration.

    blueprint_name must be unique per instance, since Flask requires
    unique blueprint names across the app and every instance of a type
    builds a blueprint with the same constructor name (e.g. every
    ConfigUiOutput's blueprint is named "config") - but only actually
    needs disambiguating (name+index) when count > 1; the common single-
    instance case keeps the plain, readable name. Every converted output's
    templates/JS use Flask's relative url_for('.endpoint') form
    specifically so this is invisible to them either way.
    """
    base = "" if getattr(output_cls, "root_mounted", False) else f"/{name}"
    if index == 0:
        prefix = base
    else:
        if not label:
            raise ValueError(
                f"outputs.{name} has more than one instance, but instance "
                f"{index + 1} has no `label` set - every instance after the "
                f"first needs one so they don't collide on the same URL "
                f'(e.g. label: "{name}2"). See the `label` field under '
                f"outputs.{name} in config.yaml."
            )
        prefix = f"{base}-{label}" if base else f"/{label}"
    blueprint_name = name if count == 1 else f"{name}{index}"
    return prefix, blueprint_name


def instantiate_outputs(
    config: Config,
    config_path: Path,
    cache: ImageCache,
    shared_server: Optional[SharedHttpServer] = None,
) -> list:
    outputs = []
    for name, output_configs in config.outputs.items():
        output_cls = registries.get_output_class(name)
        if output_cls is None:
            logger.warning("Unknown output: %s", name)
            continue
        extra_args = registries.OUTPUT_EXTRA_ARGS.get(name, lambda _config, _path, _cache: ())(
            config, config_path, cache
        )
        enabled_count = sum(1 for c in output_configs if c.enabled)
        index = 0
        for output_config in output_configs:
            if not output_config.enabled:
                continue
            output = output_cls(output_config, *extra_args)
            output.start()
            # Only Flask-based outputs (those overriding build_http_blueprint)
            # need a URL prefix/label-collision check - a non-HTTP output
            # (pixoo, ulanzi, folder, mqtt, ...) never mounts anything on the
            # shared server, so requiring a `label` on its 2nd+ instance would
            # be an unrelated, surprising restriction. See Output.
            # build_http_blueprint()'s docstring for the "Flask-based only"
            # contract this checks.
            is_http_output = (
                getattr(output_cls, "build_http_blueprint", None) is not Output.build_http_blueprint
            )
            if shared_server is not None and is_http_output:
                url_prefix, blueprint_name = _compute_url_mount(
                    name, index, enabled_count, output_cls, getattr(output_config, "label", "")
                )
                blueprint = output.build_http_blueprint(url_prefix, sock=shared_server.sock)
                if blueprint is not None:
                    shared_server.register_blueprint(
                        blueprint, url_prefix=url_prefix, name=blueprint_name
                    )
            outputs.append(output)
            index += 1
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
    MediaDataArtworkEnricher and MediaDataLyricsEnricher (both declare
    `capabilities = frozenset({"mediadata"})` - see build_enrichers()/
    build_text_enrichers() below), or None if neither plugin is enabled -
    so a config that doesn't opt in never even touches disk for this
    feature."""
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
        capabilities: frozenset = getattr(enricher_cls, "capabilities", frozenset())
        if "library" in capabilities:
            enrichers.append(enricher_cls(enricher_config, library))
        elif "cache_dir" in capabilities:
            enrichers.append(enricher_cls(enricher_config, Path(config.cache.dir) / "ai_artwork"))
        elif "mediadata" in capabilities:
            enrichers.append(enricher_cls(enricher_config, mediadata_store))
        else:
            enrichers.append(enricher_cls(enricher_config))
    return enrichers


def build_text_enrichers(config: Config, mediadata_store: Optional[MediaDataStore] = None) -> list:
    """Build the configured text enrichers (lyrics, AI-generated text -
    see mediainfo/enrichers/text_base.py), each sharing one TextCache
    instance under cache.dir/text (same retention as artwork, mirroring
    ImageCache's own idle/music subdirectories) - except plugins declaring
    `capabilities = frozenset({"mediadata"})` (e.g. MediaDataLyricsEnricher),
    which read the shared MediaDataStore instead."""
    text_cache = TextCache(Path(config.cache.dir) / "text", max_age_days=config.cache.max_age_days)
    text_enrichers = []
    for name, text_enricher_config in config.text_enrichers.items():
        if not text_enricher_config.enabled:
            continue
        text_enricher_cls = registries.get_text_enricher_class(name)
        if text_enricher_cls is None:
            logger.warning("Unknown text enricher: %s", name)
            continue
        if "mediadata" in getattr(text_enricher_cls, "capabilities", frozenset()):
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
        if "library" in getattr(idle_cls, "capabilities", frozenset()):
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


# Sentinel distinguishing "caller didn't pass this" from "caller passed
# an explicit value" for start_orchestrator()'s pre-built-collaborator
# params below - unlike the other params here, None is a legitimate built
# value for mediadata_store/idle_source (e.g. no idle providers enabled),
# so it can't double as "please build one".
_UNSET = object()


def start_orchestrator(
    config: Config,
    outputs: list,
    cache: ImageCache,
    library: Optional[MusicLibrary] = None,
    overrides: Optional[ArtworkOverrideStore] = None,
    poster_store: Optional[PosterStore] = None,
    history: Optional[PlaybackHistory] = None,
    mediadata_store: Any = _UNSET,
    sources: Any = _UNSET,
    enrichers: Any = _UNSET,
    text_enrichers: Any = _UNSET,
    idle_source: Any = _UNSET,
) -> Orchestrator:
    """Build (unless already supplied) every collaborator the Orchestrator
    needs and start it.

    sources/enrichers/text_enrichers/idle_source/mediadata_store each
    default to building fresh from *config*, exactly as before this
    docstring existed - the only caller that passes any of them explicitly
    is __main__.py's _start_and_wire(), on a config hot-reload, to reuse
    whatever collaborator N7's ReloadPlan (see mediainfo/reload_plan.py)
    says didn't need rebuilding, instead of tearing down and reconnecting
    every source/enricher/idle provider on every reload regardless of what
    actually changed.
    """
    if mediadata_store is _UNSET:
        mediadata_store = build_mediadata_store(config, cache)
    if sources is _UNSET:
        sources = build_sources(config)
    if enrichers is _UNSET:
        enrichers = build_enrichers(config, library, mediadata_store)
    if text_enrichers is _UNSET:
        text_enrichers = build_text_enrichers(config, mediadata_store)
    if idle_source is _UNSET:
        idle_source = build_idle_source(config, library)
    orch = Orchestrator(
        sources=sources,
        enrichers=enrichers,
        text_enrichers=text_enrichers,
        outputs=outputs,
        cache=cache,
        poll_interval_seconds=config.poll_interval_seconds,
        rotation_interval_seconds=config.rotation_interval_seconds,
        idle_source=idle_source,
        backoff_initial_seconds=config.backoff_initial_seconds,
        backoff_max_seconds=config.backoff_max_seconds,
        nothing_playing_grace_seconds=config.nothing_playing_grace_seconds,
        enrichment_deadline_seconds=config.enrichment_deadline_seconds,
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
