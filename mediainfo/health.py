"""Builds the /health JSON payload: per-source/output/enricher/idle-source
status, layered on top of Orchestrator.get_health()'s raw counters.

This payload is a public, versioned API (N8 in
docs/architecture-usability-review-2026-07.md) - it's polled by anything
scraping /health directly (monitoring, HA, MQTT's health-state topic, see
outputs/mqtt.py), and doubles as the new dashboard's own data source (see
outputs/ui_builder.py, which reads sources/outputs/enrichers/idle_sources
straight out of this dict rather than recomputing status itself). See
docs/health-api-reference.md for the full field-by-field schema.

Versioning contract, mirroring config_version's (see README.md):
adding a new top-level or per-entry field is NOT a breaking change and
does not bump HEALTH_SCHEMA_VERSION - consumers must already tolerate
unknown keys. Removing or renaming a field documented in
docs/health-api-reference.md, or changing its type/meaning, is breaking
and must bump HEALTH_SCHEMA_VERSION.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from mediainfo import registries
from mediainfo.config import Config
from mediainfo.idle.composite import CompositeIdleWallpaperSource
from mediainfo.orchestrator import Orchestrator
from mediainfo.outputs.config_schema import _is_secret
from mediainfo.status import AvailabilityReason, Health, translate_availability

# Bump only for a breaking change to a field documented in
# docs/health-api-reference.md (removed/renamed/retyped) - see this
# module's own docstring. Never bump for a purely additive change.
HEALTH_SCHEMA_VERSION = 1


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


def _reason_for_source(source, backed_off: bool, is_active: bool) -> AvailabilityReason:
    """The AvailabilityReason behind a source's entry - see
    mediainfo/status.py for the Health/Activity model this feeds. A
    migrated source's own reported reason is trusted outright; an
    unmigrated one (availability_reason still None - see
    MediaSource.availability_reason) falls back to the same binary
    backoff-based read health.py has always used, so its raw status
    below comes out byte-identical to before Fas 10."""
    if source.availability_reason is not None:
        return source.availability_reason
    if backed_off:
        return AvailabilityReason.API_ERROR
    return AvailabilityReason.PLAYING if is_active else AvailabilityReason.IDLE


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
        # not_configured for everything else in the registry. Health/
        # Activity (see mediainfo/status.py): a migrated source's own
        # availability_reason is trusted outright, so a healthy-but-off
        # device reads as "idle"/Healthy, not "error" - an unmigrated
        # source falls back to the same binary backoff read as before
        # Fas 10, so its raw status here is unchanged.
        backoff_seconds = data["source_backoff_seconds"]
        failing_for_seconds = data["source_failing_for_seconds"]
        active_source_names = {s.name for s in orch.sources}
        sources = []
        for source in orch.sources:
            backed_off = source.name in backoff_seconds
            is_active = source.name == active_source
            device_status = translate_availability(
                _reason_for_source(source, backed_off, is_active)
            )
            if device_status.health == Health.ERROR:
                status = "error"
            elif device_status.health == Health.WARNING:
                status = "warning"
            else:
                status = "active" if is_active else "idle"
            entry: dict = {
                "name": source.name,
                "status": status,
                "activity": device_status.activity.value,
                "activity_label": device_status.label,
            }
            if source.name in polled_ago:
                entry["last_polled_ago_seconds"] = polled_ago[source.name]
            if backed_off:
                retry = backoff_seconds[source.name]
                entry["retry_in_seconds"] = retry
                entry["failing_for_seconds"] = failing_for_seconds.get(source.name, 0)
            if device_status.health != Health.HEALTHY:
                # Healthy (including a sleeping/powered-off device) never
                # gets a warning message - Health should only indicate
                # actual problems.
                entry["last_error"] = device_status.label
            entry.update(config_detail_fields(config.sources.get(source.name)))
            entry.update(source.health_check() or {})
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
            entry.update(output.health_check() or {})
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
            entry.update(enricher.health_check() or {})
            enrichers.append(entry)
        enrichers.extend(
            _registered_but_inactive(
                active_enricher_names, registries.ENRICHER_CLASSES, config.enrichers
            )
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
            name = instance.name or type(instance).__name__.removesuffix("WallpaperSource").lower()
            active_idle_names.add(name)
            idle_entry = {
                "type": name,
                "status": "ok",
                "wallpapers_loaded": data["idle_wallpapers_loaded"],
            }
            idle_entry.update(instance.health_check() or {})
            idle_sources.append(idle_entry)
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
            "schema_version": HEALTH_SCHEMA_VERSION,
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
