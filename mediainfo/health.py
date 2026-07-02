"""Builds the /health JSON payload: per-source/output/enricher/idle-source
status, layered on top of Orchestrator.get_health()'s raw counters.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from mediainfo import registries
from mediainfo.config import Config
from mediainfo.idle.composite import CompositeIdleWallpaperSource
from mediainfo.orchestrator import Orchestrator
from mediainfo.outputs.config_ui import _is_secret


def config_detail_fields(cfg: Any) -> dict:
    """Non-secret str/int/bool config fields with a non-empty value - shown
    on a source/enricher's dashboard card alongside its status."""
    if cfg is None:
        return {}
    detail = {}
    for f in dataclasses.fields(type(cfg)):
        if f.name == "enabled" or f.type not in ("bool", "int", "str") or _is_secret(f.name):
            continue
        val = getattr(cfg, f.name, None)
        if val not in (None, ""):
            detail[f.name] = val
    return detail


def _registered_but_inactive(active_names: set, registry: dict, config_section: dict) -> list:
    """Entries for every key/source/enricher registry entry that isn't
    already active: "disabled" (with its config detail fields) if it has
    a config section at all, else "not_configured". Shared by sources and
    enrichers, which key by "name" and have one config dataclass each."""
    entries = []
    for name in registry:
        if name in active_names:
            continue
        cfg = config_section.get(name)
        if cfg is not None:
            entry = {"name": name, "status": "disabled"}
            entry.update(config_detail_fields(cfg))
            entries.append(entry)
        else:
            entries.append({"name": name, "status": "not_configured"})
    return entries


def _inactive_outputs(active_types: set, registry: dict, config_outputs: dict) -> list:
    """Entries for every output type with no active instance - "disabled"
    if it has a (possibly empty) config list, else "not_configured"."""
    entries = []
    for type_name in registry:
        if type_name in active_types:
            continue
        status = "disabled" if config_outputs.get(type_name) else "not_configured"
        entries.append({"type": type_name, "status": status, "instance_index": 0})
    return entries


def _inactive_idle_sources(active_names: set, registry: dict, config_idle: dict) -> list:
    """Entries for every idle wallpaper source not already part of the
    active pool - "ok"/"disabled" if configured (matching the config's own
    enabled flag, since multiple idle sources can be enabled and merged at
    once), else "not_configured"."""
    entries = []
    for name in registry:
        if name in active_names:
            continue
        idle_cfg = config_idle.get(name)
        if idle_cfg is not None:
            status = "disabled" if not idle_cfg.enabled else "ok"
        else:
            status = "not_configured"
        entries.append({"type": name, "status": status})
    return entries


def make_health_provider(orch: Orchestrator, config: Config, outputs: list):
    """Return a callable that builds the full /health JSON dict."""

    def _health() -> dict:
        data = orch.get_health()
        active_source = data["active_source"]
        polled_ago = data["source_last_polled_ago"]
        output_errors = data["output_errors"]

        # Sources — active/idle for those in the orchestrator; disabled /
        # not_configured for everything else in the registry.
        backoff_seconds = data["source_backoff_seconds"]
        active_source_names = {s.name for s in orch.sources}
        sources = []
        for source in orch.sources:
            status = "active" if source.name == active_source else "idle"
            if source.name in backoff_seconds:
                status = "error"
            entry: dict = {"name": source.name, "status": status}
            if source.name in polled_ago:
                entry["last_polled_ago_seconds"] = polled_ago[source.name]
            if source.name in backoff_seconds:
                retry = backoff_seconds[source.name]
                entry["retry_in_seconds"] = retry
                entry["last_error"] = f"Could not connect - retrying in {retry}s"
            entry.update(config_detail_fields(config.sources.get(source.name)))
            sources.append(entry)
        sources.extend(
            _registered_but_inactive(active_source_names, registries.SOURCE_CLASSES, config.sources)
        )

        # Outputs
        active_output_types: set = set()
        output_type_counts: dict = {}
        output_list = []
        for i, output in enumerate(outputs):
            cls = type(output)
            type_name = registries.output_name_for_class(cls) or cls.__name__
            active_output_types.add(type_name)
            instance_index = output_type_counts.get(type_name, 0)
            output_type_counts[type_name] = instance_index + 1
            err = output_errors.get(i)
            entry = {
                "type": type_name,
                "status": "error" if err else "ok",
                "instance_index": instance_index,
            }
            if err:
                entry["last_error"] = err["message"]
                entry["last_error_ago_seconds"] = err["ago_seconds"]
            binding = data.get("output_now_playing", {}).get(i)
            if binding:
                # Which item this output is bound to - with per-output
                # source routing, different outputs can show different
                # sources at once.
                entry["now_playing"] = f"{binding['source']}: {binding['title']}"
            cfg = getattr(output, "config", None)
            if cfg:
                for field in registries.OUTPUT_DETAIL_FIELDS.get(type_name, []):
                    val = getattr(cfg, field, None)
                    if val not in (None, ""):
                        entry[field] = val
            output_list.append(entry)
        output_list.extend(
            _inactive_outputs(active_output_types, registries.OUTPUT_CLASSES, config.outputs)
        )

        # Enrichers
        active_enricher_names: set = set()
        enrichers = []
        for enricher in orch.enrichers:
            name = registries.enricher_name_for_class(type(enricher)) or type(enricher).__name__
            active_enricher_names.add(name)
            entry = {"name": name, "status": "ok"}
            entry.update(config_detail_fields(config.enrichers.get(name)))
            enrichers.append(entry)
        enrichers.extend(
            _registered_but_inactive(active_enricher_names, registries.ENRICHER_CLASSES, config.enrichers)
        )

        # Idle sources — list of all known idle sources with their status.
        idle_sources = []

        # Traditional wallpaper idle sources (IDLE_CLASSES registry). When
        # several are enabled at once, orch.idle_source is a
        # CompositeIdleWallpaperSource wrapping all of them - exactly one
        # of them supplies any given batch (see idle/composite.py), but
        # wallpapers_loaded below reports the shared current-batch size
        # under every configured source's name regardless of which one
        # actually supplied it.
        if isinstance(orch.idle_source, CompositeIdleWallpaperSource):
            active_idle_instances = orch.idle_source.sources
        elif orch.idle_source is not None:
            active_idle_instances = [orch.idle_source]
        else:
            active_idle_instances = []

        active_idle_names: set = set()
        for instance in active_idle_instances:
            name = type(instance).__name__.removesuffix("WallpaperSource").lower()
            active_idle_names.add(name)
            idle_sources.append({
                "type": name,
                "status": "ok",
                "wallpapers_loaded": data["idle_wallpapers_loaded"],
            })
        idle_sources.extend(
            _inactive_idle_sources(active_idle_names, registries.IDLE_CLASSES, config.idle)
        )

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
            "hitster_safe": data["hitster_safe"],
            "sources": sources,
            "outputs": output_list,
            "enrichers": enrichers,
            "idle_sources": idle_sources,
        }

    return _health
