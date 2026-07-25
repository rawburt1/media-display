"""Reads and writes config.yaml for the config UI: flat dotted-key values
for the form, the (possibly multi-instance) outputs section, the
`ui_hidden_types` display preference, and the guided-form/raw-YAML save
paths (both always validated via Config.from_dict() before anything is
written).

Split out of config_ui.py. Shares its caller's lock (config.yaml access
needs to be serialized across the whole ConfigUiOutput, including the
library browser and Apple TV credential saves, not just this store) rather
than owning its own.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from mediainfo.config import OUTPUT_CONFIG_TYPES, Config
from mediainfo.config_backup import backup_config_file, list_backups, restore_backup
from mediainfo.config_error_translator import friendly_config_error
from mediainfo.web_auth import hash_password
from mediainfo.configui.config_schema import (
    _FLAT_SECTIONS,
    _GENERAL_FIELDS,
    _HIDDEN_TYPE_CATEGORIES,
    _LABEL_FIELD_NAME,
    _SINGLE_INSTANCE_CATEGORIES,
    _as_instance_list,
    _clean_output_filter_defaults,
    _get_filter_values,
    _scalar_fields,
    _validate_filter_fields,
)
from mediainfo.configui.config_yaml_io import _dump_config, _read_config, _yaml

logger = logging.getLogger(__name__)


class ConfigStore:
    def __init__(self, config_path: Path, lock: threading.Lock):
        self.config_path = config_path
        self._lock = lock

    def get_values(self):
        """Flat dotted-key values for the single-instance categories
        (general/flat sections/sources/enrichers/idle), plus a parallel
        `secrets_set` map. See get_output_instances() for the (possibly
        multi-instance) outputs category.

        Secret fields (schema field["secret"]) never carry their real
        value here - the value is always "" and `secrets_set[key]` reports
        whether one is actually configured, so the browser can show
        "Configured" without ever receiving the credential itself.
        """
        with self._lock:
            data = _read_config(self.config_path)

        values: Dict[str, Any] = {}
        secrets_set: Dict[str, bool] = {}
        for name, field_type, default in _GENERAL_FIELDS:
            values[f"general.{name}"] = data.get(name, default)

        for section_name, cls in _FLAT_SECTIONS.items():
            flat_entry = data.get(section_name) or {}
            for field in _scalar_fields(cls, "flat", section_name):
                key = f"{section_name}.{field['name']}"
                raw = flat_entry.get(field["name"], field["default"])
                if field["secret"]:
                    secrets_set[key] = bool(raw)
                    values[key] = ""
                else:
                    values[key] = raw

        for category, registry in _SINGLE_INSTANCE_CATEGORIES.items():
            section = data.get(category) or {}
            for type_name, cls in registry.items():
                entry = section.get(type_name) or {}
                for field in _scalar_fields(cls, category, type_name):
                    key = f"{category}.{type_name}.{field['name']}"
                    raw = entry.get(field["name"], field["default"])
                    if field["secret"]:
                        secrets_set[key] = bool(raw)
                        values[key] = ""
                    else:
                        values[key] = raw
        return values, secrets_set

    def get_output_instances(self):
        """Return ({output_type: [instance_field_values, ...]}, secrets_set)
        for every registered output type, with at least one (possibly
        all-default) instance per type so the form always has something to
        render.

        Each instance dict includes scalar fields, filter fields, and the
        cosmetic `label` field, so the UI can read/write them all together.
        Secret fields are blanked exactly as in get_values() - see there
        for why.
        """
        with self._lock:
            data = _read_config(self.config_path)

        section = data.get("outputs") or {}
        result: Dict[str, List[Dict[str, Any]]] = {}
        secrets_set: Dict[str, bool] = {}
        for type_name, cls in OUTPUT_CONFIG_TYPES.items():
            instances = _as_instance_list(section.get(type_name)) or [{}]
            fields = _scalar_fields(cls, "outputs", type_name)
            out_instances = []
            for idx, instance in enumerate(instances):
                entry: Dict[str, Any] = {}
                for f in fields:
                    key = f"outputs.{type_name}.{idx}.{f['name']}"
                    raw = instance.get(f["name"], f["default"])
                    if f["secret"]:
                        secrets_set[key] = bool(raw)
                        entry[f["name"]] = ""
                    else:
                        entry[f["name"]] = raw
                entry.update(_get_filter_values(instance))
                entry[_LABEL_FIELD_NAME] = instance.get(_LABEL_FIELD_NAME, "")
                if type_name == "themes":
                    # ThemesConfig.themes is a raw dict (one entry per
                    # individual theme plugin), deliberately excluded from
                    # _scalar_fields() like `transforms` elsewhere - but
                    # unlike transforms, the themes picker (app.html's
                    # renderThemesPicker) needs it, so pass it through
                    # as-is here rather than leaving it YAML-only. Not
                    # validated/defaulted (mirrors every other field on
                    # this path) - mediainfo.config.themes.parse_themes()
                    # does that at actual app startup.
                    entry["themes"] = instance.get("themes") or {}
                    # auto_rotate.presets can hold either shape (a plain
                    # list of theme names, or {"themes": [...],
                    # "when": [...]}) - same raw pass-through as `themes`
                    # above, so the groups editor UI can read/write it
                    # whole without this layer needing to know its
                    # internal shape. mediainfo.config.outputs.
                    # parse_presets() validates it at actual app startup.
                    entry["auto_rotate"] = instance.get("auto_rotate") or {}
                out_instances.append(entry)
            result[type_name] = out_instances
        return result, secrets_set

    def get_hidden_types(self) -> Dict[str, List[str]]:
        """Plugin type names hidden from the Media sources/Displays &
        outputs/Artwork & metadata cards - purely a display preference
        (doesn't affect whether a type is enabled/used), stored under the
        `ui_hidden_types` top-level key, which Config doesn't model at all
        (unknown top-level keys are silently ignored by Config.from_dict)
        so this never needs a restart or touches any plugin's behavior.
        """
        with self._lock:
            data = _read_config(self.config_path)
        raw = data.get("ui_hidden_types") or {}
        return {
            category: [n for n in (raw.get(category) or []) if isinstance(n, str)]
            for category in _HIDDEN_TYPE_CATEGORIES
        }

    def set_hidden_type(self, category: str, name: str, hidden: bool) -> Optional[str]:
        """Add/remove `name` from the hidden-types list for `category`.
        Returns an error message on failure, or None on success.
        """
        with self._lock:
            data = _read_config(self.config_path)
            section = data.setdefault("ui_hidden_types", {})
            names = [n for n in (section.get(category) or []) if isinstance(n, str)]
            if hidden and name not in names:
                names.append(name)
            elif not hidden and name in names:
                names.remove(name)
            if names:
                section[category] = names
            else:
                section.pop(category, None)
            if not section:
                data.pop("ui_hidden_types", None)

            try:
                Config.from_dict(data)
            except Exception as exc:
                logger.warning("Rejected hidden-types update: %s", exc)
                return friendly_config_error(exc)

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            backup_config_file(self.config_path)
            with self.config_path.open("w", encoding="utf-8") as f:
                f.write(_dump_config(data))
        return None

    def save_form(
        self, values: Dict[str, Any], outputs: Dict[str, List[Dict[str, Any]]]
    ) -> Tuple[Optional[str], bool, FrozenSet[str]]:
        """Merge posted form data into config.yaml. Returns
        (error_message, restart_required, changed_output_types);
        error_message is None on success.

        changed_output_types is the subset of `outputs`' keys that are
        registered output types (see OUTPUT_CONFIG_TYPES) and were
        actually merged - the per-output-type refinement behind
        UiComponent.requires_restart/status (see ui_builder.
        _output_components and ConfigUiOutput._restart_required_outputs).
        `restart_required` itself stays the same blanket "any output
        section touched, or auth touched" bool it always was - see the
        comment below.
        """
        with self._lock:
            data = _read_config(self.config_path)

            self._merge_single_instance_fields(data, values)

            changed_output_types: Set[str] = set()
            for type_name, instances in outputs.items():
                if type_name not in OUTPUT_CONFIG_TYPES:
                    continue
                self._merge_output_instances(data, type_name, instances)
                changed_output_types.add(type_name)

            # Validate filter fields before any write.
            filter_error = _validate_filter_fields(data)
            if filter_error:
                logger.warning("Rejected config form save (filter): %s", filter_error)
                return filter_error, False, frozenset()

            # Strip filter fields that are at their no-restriction defaults
            # so existing config files stay tidy.
            _clean_output_filter_defaults(data)

            try:
                Config.from_dict(data)
            except Exception as exc:
                logger.warning("Rejected config form save: %s", exc)
                return friendly_config_error(exc), False, frozenset()

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            backup_config_file(self.config_path)
            with self.config_path.open("w", encoding="utf-8") as f:
                f.write(_dump_config(data))

            # `outputs` (added/removed/reconfigured instances) and `auth`
            # both need a restart - outputs are only instantiated once at
            # startup, and every Flask-based output's HTTP Basic Auth
            # check (install_auth(), see config_ui.py's _build_app())
            # closes over the AuthConfig instance passed in at that same
            # startup, which the regular hot-reload never re-wires onto
            # already-running servers. Everything else (sources/enrichers/
            # idle/general/cache/etc.) picks up via hot-reload without a
            # restart.
            restart_required = bool(changed_output_types) or any(
                key.startswith("auth.") for key in values
            )
        return None, restart_required, frozenset(changed_output_types)

    @staticmethod
    def _merge_single_instance_fields(data: Any, values: Dict[str, Any]) -> None:
        """Write posted "general"/flat-section/single-instance (sources,
        enrichers, idle) field values - keys of the form "general.<field>",
        "<flat_section>.<field>" (e.g. "cache.min_width"), or
        "<category>.<type_name>.<field_name>" - into `data` in place.

        A key simply absent from `values` is left untouched in `data` -
        this is what lets the client omit an unmodified secret field
        entirely and have its existing value survive the save unchanged.
        """
        for key, value in values.items():
            parts = key.split(".")

            if len(parts) == 2 and parts[0] == "general":
                data[parts[1]] = value
                continue

            if len(parts) == 2 and parts[0] in _FLAT_SECTIONS:
                if key == "auth.password":
                    # Every write path hashes before persisting (M1 in
                    # docs/architecture-usability-review-2026-07.md) -
                    # config.yaml never gets a plaintext password from
                    # here, matching set-password's own behavior. Only
                    # reached when the client actually posted a new value
                    # (see this method's own docstring: an untouched
                    # secret field is simply absent from `values`), so
                    # this never re-hashes the existing stored hash.
                    value = hash_password(value)
                section = data.setdefault(parts[0], {})
                section[parts[1]] = value
                continue

            if len(parts) != 3:
                continue
            category, type_name, field_name = parts
            if (
                category not in _SINGLE_INSTANCE_CATEGORIES
                or type_name not in _SINGLE_INSTANCE_CATEGORIES[category]
            ):
                continue

            section = data.setdefault(category, {})
            entry = section.get(type_name)
            entry = entry if isinstance(entry, dict) else {}
            entry[field_name] = value
            section[type_name] = entry

    @staticmethod
    def _merge_output_instances(
        data: Any, type_name: str, posted_instances: List[Dict[str, Any]]
    ) -> None:
        """Write `posted_instances` (one dict of field values per instance,
        in order) for `type_name` into `data["outputs"]`.

        Existing instances are mutated in place (preserving non-form fields
        like `transforms` and any YAML comments) rather than replaced, for
        every position present in both the existing and posted lists.
        Posted instances beyond the existing count are brand new (plain
        dicts); existing instances beyond the posted count are dropped -
        i.e. instances can only be appended or removed from the end.

        As in _merge_single_instance_fields, a field key absent from a
        posted instance is left untouched on the existing instance - the
        client relies on this to omit untouched secret fields.
        """
        section = data.setdefault("outputs", {})
        existing_instances = _as_instance_list(section.get(type_name))

        merged = []
        for i, posted in enumerate(posted_instances):
            if i < len(existing_instances):
                instance = existing_instances[i]
                for field_name, value in posted.items():
                    instance[field_name] = value
            else:
                instance = dict(posted)
            merged.append(instance)
        section[type_name] = merged

    def save_raw(self, raw_yaml: str) -> Tuple[Optional[str], bool, FrozenSet[str]]:
        """Returns (error_message, restart_required, changed_output_types)."""
        try:
            parsed = _yaml.load(raw_yaml) or {}
            Config.from_dict(parsed)
        except Exception as exc:
            logger.warning("Rejected raw config save: %s", exc)
            return friendly_config_error(exc), False, frozenset()

        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            backup_config_file(self.config_path)
            with self.config_path.open("w", encoding="utf-8") as f:
                f.write(raw_yaml)
        # A raw save can change anything, including outputs - safest to
        # assume a restart might be needed rather than silently miss one,
        # and (since raw YAML isn't diffed field-by-field like the guided
        # form's outputs) to mark every registered output type as pending
        # rather than guessing which one(s) actually changed.
        return None, True, frozenset(OUTPUT_CONFIG_TYPES.keys())

    def restore_backup(self, filename: str) -> Tuple[Optional[str], bool, FrozenSet[str]]:
        """Restore config.yaml from one of its automatic backups (see
        mediainfo.config_backup), resolving `filename` by exact match
        against list_backups() - never as a raw path, since the client
        only ever supplies a name we ourselves listed. Returns
        (error_message, restart_required, changed_output_types).
        """
        with self._lock:
            backups = list_backups(self.config_path)
            if not backups:
                return "No backups available to restore.", False, frozenset()
            matches = [b for b in backups if b.name == filename]
            if not matches:
                return f"Unknown backup: {filename!r}.", False, frozenset()
            restore_backup(self.config_path, matches[0])
        # A restored config.yaml can change anything, including outputs and
        # auth - safest to assume a restart might be needed, same reasoning
        # (and same "mark every output type" per-output fallback) as
        # save_raw's raw-YAML save.
        return None, True, frozenset(OUTPUT_CONFIG_TYPES.keys())
