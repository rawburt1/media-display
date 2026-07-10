"""Translates existing config/schema/health data into the UiComponent/
UiPipeline/UiDashboard model (ui_model.py) - see
docs/gui-redesign-phase0-inventory.md for the overall plan.

Pure functions: no Flask, no file I/O, no ConfigStore/health-provider calls
of its own - callers (config_ui.py) fetch the underlying data (schema,
masked values, health) and pass it in here, the same split already used by
config_schema.py. Nothing here re-implements field shaping, secret masking,
or required-field detection - it only reads the fields config_schema.py and
config_store.py already computed.

One gap worth calling out: `text_enrichers` (lrclib/mediadata/ollama_text)
isn't covered by config_schema._build_schema() or ConfigStore today (it's
raw-YAML-only in the legacy UI - see config_store.py, which never mentions
it). Rather than duplicate config_schema's field-shaping logic for those
three small dataclasses, this module calls config_schema._scalar_fields()
directly for them and reads their raw config values itself (safe: none of
their fields are secret).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mediainfo.config import (
    ENRICHER_CONFIG_TYPES,
    IDLE_CONFIG_TYPES,
    OUTPUT_CONFIG_TYPES,
    SOURCE_CONFIG_TYPES,
    TEXT_ENRICHER_CONFIG_TYPES,
    THEMES_CONFIG_TYPES,
)
from mediainfo.outputs import config_schema
from mediainfo.outputs.ui_model import (
    UiAction,
    UiComponent,
    UiDashboard,
    UiField,
    UiHealthSummary,
    UiPipeline,
)

# Output types that are plumbing (this running server / the appearance-theme
# host) rather than a real display target - excluded from the Displays
# category and from the pipeline's display_component_ids.
_NON_DISPLAY_OUTPUT_TYPES = frozenset({"config", "themes"})

# health.py's per-category status strings, normalized to ui_model's richer
# UiComponent.status vocabulary.
_HEALTH_STATUS_MAP = {
    "active": "connected",
    "idle": "connected",
    "ok": "connected",
    "error": "error",
    "disabled": "disabled",
    "not_configured": "needs_configuration",
}

# Display copy for components not covered by config_schema._TYPE_INFO: the
# flat single-instance sections (cache/history/... plus "general", which
# isn't even a dataclass) and text_enrichers (see module docstring).
_EXTRA_TYPE_INFO: Dict[str, Dict[str, Dict[str, str]]] = {
    "flat": {
        "cache": {
            "label": "Artwork Cache",
            "description": "Local disk cache for downloaded artwork/images.",
        },
        "history": {
            "label": "Playback History",
            "description": "Self-hosted scrobble log of everything played, across every source.",
        },
        "library": {
            "label": "Music Library Cache",
            "description": "Local SQLite cache of artist/album/track metadata, avoiding repeat external lookups.",
        },
        "overrides": {
            "label": "Artwork Overrides",
            "description": "Manual per-title artwork pins.",
        },
        "posters": {
            "label": "Poster Store",
            "description": "Static poster images matched per show.",
        },
        "mediadata": {
            "label": "Unified Media Data Cache",
            "description": "Shared on-disk artwork/lyrics/metadata cache used by the mediadata enrichers.",
        },
        "auth": {
            "label": "Authentication",
            "description": "HTTP Basic Auth for outputs reachable beyond your LAN.",
        },
        "logging": {
            "label": "Logging",
            "description": "Log level and optional log file.",
        },
        "alerts": {
            "label": "Alerts",
            "description": "Webhook notifications when a source or output has been failing for a while.",
        },
        "general": {"label": "General", "description": "Polling and rotation timing."},
    },
    "text_enrichers": {
        "lrclib": {
            "label": "LRCLIB",
            "description": "Free, public time-synced lyrics lookup - no API key needed.",
        },
        "mediadata": {
            "label": "Local Media Data Cache (lyrics)",
            "description": "Checks the local unified media-data cache for lyrics before falling back to LRCLIB.",
        },
        "ollama_text": {
            "label": "Ollama (local AI text)",
            "description": "Generates text via a local Ollama instance.",
        },
    },
}

# Which top-level GUI category each flat section belongs to (see Fas 0
# inventory doc §4.1).
_CATEGORY_FOR_FLAT_SECTION = {
    "cache": "library",
    "history": "library",
    "library": "library",
    "overrides": "library",
    "posters": "library",
    "mediadata": "library",
    "auth": "advanced",
    "logging": "advanced",
    "general": "advanced",
    "alerts": "health",
}


def _health_index(entries: Optional[List[dict]], key: str) -> Dict[str, dict]:
    """{entry[key]: entry} for the first entry seen per key - good enough
    for Fas 1's one-component-per-type scope (a type with several active
    instances, e.g. multiple outputs of the same type, collapses to its
    first health entry, same simplification as _local_map/output_instances
    below)."""
    index: Dict[str, dict] = {}
    for entry in entries or []:
        k = entry.get(key)
        if k is not None and k not in index:
            index[k] = entry
    return index


def _local_map(flat: Dict[str, Any], prefix: str) -> Dict[str, Any]:
    """Strip `prefix` off every matching key in a ConfigStore-style flat
    dotted map, e.g. {"sources.kodi.host": "x"} + "sources.kodi." ->
    {"host": "x"}."""
    plen = len(prefix)
    return {k[plen:]: v for k, v in flat.items() if k.startswith(prefix)}


def _value_with_default(raw: Dict[str, Any], field: Dict[str, Any]) -> Any:
    return raw.get(field["name"], field["default"])


def _missing_required_fields(
    fields: List[dict], local_values: Dict[str, Any], local_secrets_set: Dict[str, bool]
) -> List[str]:
    """A secret field's value is always "" in ConfigStore's masked output
    (see get_values()/get_output_instances()) whether or not one is
    actually set - so "is it missing" has to check local_secrets_set for
    secret fields, not the (always-blank) value."""
    missing = []
    for f in fields:
        if not f["required"]:
            continue
        is_set = (
            bool(local_secrets_set.get(f["name"]))
            if f["secret"]
            else bool(local_values.get(f["name"]))
        )
        if not is_set:
            missing.append(f["name"])
    return missing


def _build_fields(
    fields: List[dict], local_values: Dict[str, Any], local_secrets_set: Dict[str, bool]
) -> tuple[List[UiField], List[UiField]]:
    essential: List[UiField] = []
    advanced: List[UiField] = []
    for f in fields:
        uf = UiField(
            name=f["name"],
            label=f["label"],
            help=f["help"],
            type=f["type"],
            required=f["required"],
            secret=f["secret"],
            essential=f["essential"],
            value="" if f["secret"] else local_values.get(f["name"]),
            secret_set=bool(local_secrets_set.get(f["name"], False))
            if f["secret"]
            else False,
            default=f["default"],
            widget=f.get("widget"),
            choices=f.get("choices"),
        )
        (essential if f["essential"] else advanced).append(uf)
    return essential, advanced


def _status_for(
    enabled: bool, missing_required: List[str], health_entry: Optional[dict]
) -> str:
    if not enabled:
        return "disabled"
    if missing_required:
        return "needs_configuration"
    if health_entry is not None:
        return _HEALTH_STATUS_MAP.get(health_entry.get("status", ""), "unknown")
    return "enabled"


def _warnings_for(
    enabled: bool, missing_required: List[str], health_entry: Optional[dict]
) -> List[str]:
    """Only surfaces issues for enabled components - a disabled component
    with unfilled fields isn't a warning (matches _compute_overview's
    existing "needs attention" semantics: only enabled-but-broken things
    are actionable)."""
    warnings = []
    if enabled and missing_required:
        warnings.append(f"Missing required setting(s): {', '.join(missing_required)}")
    if health_entry and health_entry.get("last_error"):
        warnings.append(str(health_entry["last_error"]))
    return warnings


def _default_actions(supports_test: bool, test_href: Optional[str]) -> List[UiAction]:
    actions = [UiAction(id="configure", label="Configure", kind="link", href="/form")]
    if supports_test:
        actions.append(
            UiAction(id="test", label="Test connection", kind="test", href=test_href)
        )
    return actions


def _registry_components(
    section_key: str,
    registry: Dict[str, type],
    category: str,
    component_type: str,
    schema_section: Dict[str, List[dict]],
    values: Dict[str, Any],
    secrets_set: Dict[str, bool],
    health_by_key: Dict[str, dict],
    supports_test: bool,
    test_href_fmt: Optional[str],
) -> List[UiComponent]:
    components = []
    for type_name in registry:
        fields = schema_section.get(type_name, [])
        prefix = f"{section_key}.{type_name}."
        local_values = _local_map(values, prefix)
        local_secrets = _local_map(secrets_set, prefix)
        essential, advanced = _build_fields(fields, local_values, local_secrets)
        enabled = bool(local_values.get("enabled"))
        missing = _missing_required_fields(fields, local_values, local_secrets)
        health_entry = health_by_key.get(type_name)
        info = config_schema._TYPE_INFO.get(section_key, {}).get(type_name, {})
        config_path = f"{section_key}.{type_name}"
        components.append(
            UiComponent(
                id=config_path,
                name=info.get("label", type_name),
                category=category,
                component_type=component_type,
                description=info.get("description", ""),
                enabled=enabled,
                configured=not missing,
                status=_status_for(enabled, missing, health_entry),
                health=(health_entry or {}).get("status", "unknown"),
                config_path=config_path,
                supports_test=supports_test,
                supports_multiple=False,
                requires_restart=False,
                essential_fields=essential,
                advanced_fields=advanced,
                warnings=_warnings_for(enabled, missing, health_entry),
                actions=_default_actions(
                    supports_test,
                    test_href_fmt.format(type_name) if test_href_fmt else None,
                ),
            )
        )
    return components


def _output_components(
    schema_outputs: Dict[str, List[dict]],
    output_instances: Dict[str, List[dict]],
    output_secrets_set: Dict[str, bool],
    health_by_type: Dict[str, dict],
) -> List[UiComponent]:
    components = []
    for type_name, cls in OUTPUT_CONFIG_TYPES.items():
        if type_name in _NON_DISPLAY_OUTPUT_TYPES:
            continue
        fields = schema_outputs.get(type_name, [])
        instances = output_instances.get(type_name) or [{}]
        instance = instances[0]
        local_secrets = _local_map(output_secrets_set, f"outputs.{type_name}.0.")
        essential, advanced = _build_fields(fields, instance, local_secrets)
        enabled = bool(instance.get("enabled"))
        missing = _missing_required_fields(fields, instance, local_secrets)
        health_entry = health_by_type.get(type_name)
        info = config_schema._TYPE_INFO.get("outputs", {}).get(type_name, {})
        config_path = f"outputs.{type_name}"
        components.append(
            UiComponent(
                id=config_path,
                name=info.get("label", type_name),
                category="display",
                component_type="output",
                description=info.get("description", ""),
                enabled=enabled,
                configured=not missing,
                status=_status_for(enabled, missing, health_entry),
                health=(health_entry or {}).get("status", "unknown"),
                config_path=config_path,
                supports_test=True,
                supports_multiple=True,
                requires_restart=True,  # output changes are what trip the global restart flag - see UiDashboard.restart_required for the live signal
                essential_fields=essential,
                advanced_fields=advanced,
                warnings=_warnings_for(enabled, missing, health_entry)
                + (
                    [f"{len(instances)} instances configured - showing the first"]
                    if len(instances) > 1
                    else []
                ),
                actions=_default_actions(True, "/api/test/output"),
            )
        )
    return components


def _theme_components(
    schema_themes: Dict[str, List[dict]], output_instances: Dict[str, List[dict]]
) -> List[UiComponent]:
    themes_instances = output_instances.get("themes") or [{}]
    themes_enabled = bool(themes_instances[0].get("enabled"))
    raw_themes: Dict[str, Any] = themes_instances[0].get("themes") or {}
    components = []
    for theme_name in THEMES_CONFIG_TYPES:
        fields = schema_themes.get(theme_name, [])
        raw = raw_themes.get(theme_name) or {}
        local_values = {f["name"]: _value_with_default(raw, f) for f in fields}
        essential, advanced = _build_fields(fields, local_values, {})
        enabled = themes_enabled and bool(local_values.get("enabled"))
        info = config_schema._TYPE_INFO.get("themes", {}).get(theme_name, {})
        config_path = f"themes.{theme_name}"
        components.append(
            UiComponent(
                id=config_path,
                name=info.get("label", theme_name),
                category="appearance",
                component_type="theme",
                description=info.get("description", ""),
                enabled=enabled,
                configured=True,
                status="enabled" if enabled else "disabled",
                health="unknown",
                config_path=config_path,
                supports_test=False,
                supports_multiple=False,
                requires_restart=False,
                essential_fields=essential,
                advanced_fields=advanced,
                warnings=[],
                actions=_default_actions(False, None),
            )
        )
    return components


def _text_enricher_components(text_enrichers_raw: Dict[str, Any]) -> List[UiComponent]:
    components = []
    for type_name, cls in TEXT_ENRICHER_CONFIG_TYPES.items():
        fields = config_schema._scalar_fields(cls, "text_enrichers", type_name)
        raw = text_enrichers_raw.get(type_name) or {}
        local_values = {f["name"]: _value_with_default(raw, f) for f in fields}
        essential, advanced = _build_fields(fields, local_values, {})
        enabled = bool(local_values.get("enabled"))
        info = _EXTRA_TYPE_INFO["text_enrichers"].get(type_name, {})
        config_path = f"text_enrichers.{type_name}"
        components.append(
            UiComponent(
                id=config_path,
                name=info.get("label", type_name),
                category="metadata",
                component_type="text_enricher",
                description=info.get("description", ""),
                enabled=enabled,
                configured=True,
                status="enabled" if enabled else "disabled",
                health="unknown",
                config_path=config_path,
                supports_test=False,
                supports_multiple=False,
                requires_restart=False,
                essential_fields=essential,
                advanced_fields=advanced,
                warnings=[],
                actions=_default_actions(False, None),
            )
        )
    return components


def _flat_section_components(
    schema: dict, values: Dict[str, Any], text_enrichers_raw: Dict[str, Any]
) -> List[UiComponent]:
    components = []
    for section_key, info in _EXTRA_TYPE_INFO["flat"].items():
        fields = schema.get(section_key, [])
        prefix = f"{section_key}."
        local_values = _local_map(values, prefix)
        essential, advanced = _build_fields(fields, local_values, {})
        has_enabled_field = any(f["name"] == "enabled" for f in fields)
        if section_key == "mediadata":
            # MediaDataConfig has no on/off switch of its own - it's a
            # shared path/cache-policy config used by the opt-in
            # enrichers.mediadata / text_enrichers.mediadata plugins.
            enabled = bool(values.get("enrichers.mediadata.enabled")) or bool(
                (text_enrichers_raw.get("mediadata") or {}).get("enabled")
            )
            status = "enabled" if enabled else "disabled"
        elif has_enabled_field:
            enabled = bool(local_values.get("enabled"))
            status = "enabled" if enabled else "disabled"
        else:
            enabled = True
            status = "unknown"
        config_path = section_key
        components.append(
            UiComponent(
                id=config_path,
                name=info["label"],
                category=_CATEGORY_FOR_FLAT_SECTION[section_key],
                component_type=section_key,
                description=info["description"],
                enabled=enabled,
                configured=True,
                status=status,
                health="unknown",
                config_path=config_path,
                supports_test=False,
                supports_multiple=False,
                requires_restart=False,
                essential_fields=essential,
                advanced_fields=advanced,
                warnings=[],
                actions=_default_actions(False, None),
            )
        )
    return components


def build_components(
    schema: dict,
    values: Dict[str, Any],
    secrets_set: Dict[str, bool],
    output_instances: Dict[str, List[dict]],
    output_secrets_set: Dict[str, bool],
    text_enrichers_raw: Dict[str, Any],
    health: Optional[dict],
) -> List[UiComponent]:
    """Build every UiComponent from already-fetched config/schema/health
    data. `schema` is config_schema._build_schema()'s output; `values`/
    `secrets_set` are ConfigStore.get_values()'s two return values;
    `output_instances`/`output_secrets_set` are ConfigStore.
    get_output_instances()'s two return values; `text_enrichers_raw` is the
    raw config dict's "text_enrichers" section (see module docstring for
    why); `health` is the health provider's dict, or None if none is wired
    (e.g. most tests)."""
    health = health or {}
    sources_health = _health_index(health.get("sources"), "name")
    outputs_health = _health_index(health.get("outputs"), "type")
    enrichers_health = _health_index(health.get("enrichers"), "name")
    idle_health = _health_index(health.get("idle_sources"), "type")

    components: List[UiComponent] = []
    components += _registry_components(
        "sources",
        SOURCE_CONFIG_TYPES,
        "media",
        "source",
        schema.get("sources", {}),
        values,
        secrets_set,
        sources_health,
        supports_test=True,
        test_href_fmt="/api/test/source/{}",
    )
    components += _registry_components(
        "idle",
        IDLE_CONFIG_TYPES,
        "media",
        "idle_source",
        schema.get("idle", {}),
        values,
        secrets_set,
        idle_health,
        supports_test=False,
        test_href_fmt=None,
    )
    components += _registry_components(
        "enrichers",
        ENRICHER_CONFIG_TYPES,
        "metadata",
        "enricher",
        schema.get("enrichers", {}),
        values,
        secrets_set,
        enrichers_health,
        supports_test=True,
        test_href_fmt="/api/test/enricher/{}",
    )
    components += _text_enricher_components(text_enrichers_raw)
    components += _output_components(
        schema.get("outputs", {}), output_instances, output_secrets_set, outputs_health
    )
    components += _theme_components(schema.get("themes", {}), output_instances)
    components += _flat_section_components(schema, values, text_enrichers_raw)
    return components


def build_pipeline(components: List[UiComponent]) -> UiPipeline:
    """The single read-only "default" pipeline: enabled media sources ->
    enabled metadata enrichers -> enabled appearance themes -> enabled
    displays. Idle sources are a separate fallback path, not merged into
    this pipeline (matching the spec's own "No media playing" example being
    a distinct scenario, not a branch of the main one). Multiple pipelines
    are out of scope for Fas 1."""
    by_type: Dict[str, List[UiComponent]] = {}
    for c in components:
        by_type.setdefault(c.component_type, []).append(c)

    def _enabled_ids(component_type: str) -> List[str]:
        return [c.id for c in by_type.get(component_type, []) if c.enabled]

    return UiPipeline(
        id="default",
        name="Default media flow",
        media_component_ids=_enabled_ids("source"),
        metadata_component_ids=_enabled_ids("enricher") + _enabled_ids("text_enricher"),
        appearance_component_ids=_enabled_ids("theme"),
        display_component_ids=_enabled_ids("output"),
    )


def build_dashboard(
    components: List[UiComponent],
    pipeline: UiPipeline,
    overview: dict,
    health: Optional[dict],
) -> UiDashboard:
    health = health or {}
    counts_by_status: Dict[str, int] = {}
    warnings: List[str] = []
    for c in components:
        counts_by_status[c.status] = counts_by_status.get(c.status, 0) + 1
        for w in c.warnings:
            warnings.append(f"{c.name}: {w}")
    if overview.get("exposed_without_auth"):
        warnings.append(
            "The config UI is reachable beyond this machine with no login required."
        )

    overall_status = (
        "error" if counts_by_status.get("error") else health.get("status", "ok")
    )

    restart_required = bool(overview.get("restart_required"))
    quick_actions: List[UiAction] = []
    if restart_required:
        # Surfaced first since it's the one action that's actually
        # actionable right now - the rest are always-available links.
        quick_actions.append(
            UiAction(
                id="restart",
                label="Restart mediainfo",
                kind="restart",
                href="/api/restart",
            )
        )
    quick_actions += [
        UiAction(
            id="configure_media", label="Configure Media", kind="link", href="/form"
        ),
        UiAction(
            id="configure_metadata",
            label="Configure Metadata",
            kind="link",
            href="/form",
        ),
        UiAction(
            id="configure_appearance",
            label="Change Appearance",
            kind="link",
            href="/form",
        ),
        UiAction(
            id="configure_displays",
            label="Configure Displays",
            kind="link",
            href="/form",
        ),
        UiAction(id="open_health", label="Open Health", kind="link", href="/dashboard"),
        UiAction(
            id="open_classic_settings",
            label="Open Classic Settings",
            kind="link",
            href="/form",
        ),
    ]

    return UiDashboard(
        status=overall_status,
        now_playing=overview.get("now_playing"),
        active_source=overview.get("active_source"),
        pipeline=pipeline,
        health=UiHealthSummary(
            overall_status=overall_status,
            counts_by_status=counts_by_status,
            warnings=warnings,
        ),
        restart_required=restart_required,
        exposed_without_auth=bool(overview.get("exposed_without_auth")),
        quick_actions=quick_actions,
    )
