#!/usr/bin/env python3
"""Generates docs/config-reference.md from the config dataclasses' own
structured schema data (mediainfo/configui/config_schema.py) - the exact
same data that drives the config UI's guided form (see H5 in
docs/architecture-usability-review-2026-07.md), so this reference can
never drift from what fields actually exist, their types, defaults, and
help text.

config.example.yaml stays the hand-written, prose-and-worked-examples
reference for actually writing a config.yaml - this file is a flat,
complete field-by-field listing for looking something up quickly, not a
replacement for it.

Re-run by hand after adding/renaming/removing a config dataclass field:

    python3 scripts/generate_config_reference.py

Deterministic: re-running with no schema changes produces byte-identical
output (dict iteration order here always follows the registries'
declaration order, not something incidental like a hash).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mediainfo.configui import config_schema, ui_builder  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "docs" / "config-reference.md"


def _field_row(f: Dict[str, Any]) -> str:
    default = "" if f["secret"] else repr(f["default"])
    required = "✓" if f["required"] else ""
    secret = "✓" if f["secret"] else ""
    help_text = f["help"]
    if f.get("choices"):
        help_text = (
            (help_text + " " if help_text else "")
            + "One of: "
            + ", ".join(str(c) for c in f["choices"])
            + "."
        )
    return f"| `{f['name']}` | {f['type']} | `{default}` | {required} | {secret} | {help_text} |"


def _field_table(fields: List[Dict[str, Any]]) -> str:
    if not fields:
        return "_No configurable fields._\n"
    lines = [
        "| Field | Type | Default | Required | Secret | Help |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(_field_row(f) for f in fields)
    return "\n".join(lines) + "\n"


def _type_section(
    heading: str, name: str, fields: List[Dict[str, Any]], info: Dict[str, Any]
) -> str:
    label = info.get(name, {}).get("label", name)
    description = info.get(name, {}).get("description", "")
    out = f"### {heading} → {label}\n\n"
    if description:
        out += f"{description}\n\n"
    out += _field_table(fields) + "\n"
    return out


def _registry_sections(
    heading: str, registry: Dict[str, List[Dict[str, Any]]], info: Dict[str, Any]
) -> str:
    return "".join(_type_section(heading, name, fields, info) for name, fields in registry.items())


def generate() -> str:
    schema = config_schema._build_schema()
    type_info = schema["type_info"]

    out = [
        "# Config reference\n",
        "Generated from the config dataclasses' own field metadata (name, type, default, "
        "required, secret, help text) - see `scripts/generate_config_reference.py`. Never "
        "hand-edit this file; re-run that script instead.\n",
        "For a narrative, worked-example config with prose explanations and cross-references, "
        "see `config.example.yaml` in the project root instead - this file is a flat lookup "
        "table, not a guide.\n",
        "## General settings\n",
        _field_table(schema["general"]),
    ]

    for section in schema["flat_sections"]:
        out.append(f"## {section['title']}\n")
        out.append(_field_table(schema[section["key"]]))

    out.append("## Media sources\n")
    out.append(_registry_sections("Sources", schema["sources"], type_info["sources"]))

    out.append("## Idle screen sources\n")
    out.append(_registry_sections("Idle", schema["idle"], type_info["idle"]))

    out.append("## Displays & outputs\n")
    out.append(_registry_sections("Outputs", schema["outputs"], type_info["outputs"]))
    out.append(
        "### Content filters (every output type)\n\n"
        "Every output listed above also accepts these fields, in addition to its own - "
        'see config.example.yaml\'s "Per-output content filters" section for how they '
        "interact.\n\n"
    )
    out.append(_field_table(config_schema._output_filter_fields()))

    out.append("## Artwork & metadata enrichers\n")
    out.append(_registry_sections("Enrichers", schema["enrichers"], type_info["enrichers"]))

    out.append("## Lyrics & text enrichers\n")
    out.append(
        _registry_sections(
            "Text enrichers",
            schema["text_enrichers"],
            ui_builder._EXTRA_TYPE_INFO["text_enrichers"],
        )
    )

    out.append("## Display Themes\n")
    out.append(_registry_sections("Themes", schema["themes"], type_info["themes"]))

    return "\n".join(out)


def main() -> None:
    OUTPUT_PATH.write_text(generate(), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
