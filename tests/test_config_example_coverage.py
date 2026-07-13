"""Structural coverage check: does every field a config dataclass actually
has appear *somewhere* in config.example.yaml (active or as a commented-out
example - both count as "documented")? Catches the failure mode
config_version/migrations.py doesn't: a field renamed or added in code with
nobody updating the file real users copy from.

Deliberately NOT a value/prose rewrite - config.example.yaml's values are
worked examples (e.g. `sources.kodi.host: 192.168.1.21`), not the
dataclass's actual default (`""`), and its comments are hand-written
explanations, not generated boilerplate. This only checks field *presence*
in each type's own documented region; see scripts/generate_config_reference.py
for a fully generated (and therefore literal-default, not illustrative)
alternative.

Block extraction is text-scoped per top-level section first (`sources:`,
`outputs:`, ...), then per type within that section's own text - matching
"is this key active in the parsed YAML" would miss fields only shown in a
commented-out advanced-example block (a real, deliberately used pattern in
this file, e.g. outputs.pixoo's LED-prep settings) and produce false
positives; a single regex over the whole file would risk matching the wrong
section entirely (e.g. the top-level `library:` flat section vs.
`idle.library:`) - see docs/architecture-usability-review-2026-07.md's N1
follow-up for both false positives, found and ruled out during this
change's own design.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from mediainfo.config import (
    ENRICHER_CONFIG_TYPES,
    IDLE_CONFIG_TYPES,
    OUTPUT_CONFIG_TYPES,
    SOURCE_CONFIG_TYPES,
    TEXT_ENRICHER_CONFIG_TYPES,
)
from mediainfo.outputs import config_schema

CONFIG_EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.yaml"


def _extract_top_section(content: str, key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\n(.*?)(?=^[a-zA-Z_]+:\n|\Z)", content, re.M | re.S)
    return m.group(1) if m else ""


def _extract_type_block(section_text: str, type_name: str) -> str:
    m = re.search(
        rf"^  {re.escape(type_name)}:\n(.*?)(?=^  [a-zA-Z_]+:\n|\Z)", section_text, re.M | re.S
    )
    return m.group(1) if m is not None else ""


def _missing_fields(
    content: str, section_key: str, registry: Dict[str, type], category: str, exclude: frozenset
) -> List[str]:
    section_text = _extract_top_section(content, section_key)
    problems = []
    for name, cls in registry.items():
        fields = config_schema._scalar_fields(cls, category, name)
        field_names = [f["name"] for f in fields if f["name"] not in exclude]
        block = _extract_type_block(section_text, name)
        if not block:
            problems.append(f"{section_key}.{name}: not documented at all")
            continue
        missing = [
            n for n in field_names if not re.search(rf"^\s*#?\s*{re.escape(n)}:", block, re.M)
        ]
        if missing:
            problems.append(f"{section_key}.{name}: missing {missing}")
    return problems


def test_every_dataclass_field_is_documented_in_config_example():
    content = CONFIG_EXAMPLE.read_text(encoding="utf-8")
    problems = []
    problems += _missing_fields(content, "sources", SOURCE_CONFIG_TYPES, "sources", frozenset())
    problems += _missing_fields(
        content,
        "outputs",
        OUTPUT_CONFIG_TYPES,
        "outputs",
        config_schema._FILTER_FIELD_NAMES | {config_schema._LABEL_FIELD_NAME},
    )
    problems += _missing_fields(
        content, "enrichers", ENRICHER_CONFIG_TYPES, "enrichers", frozenset()
    )
    problems += _missing_fields(content, "idle", IDLE_CONFIG_TYPES, "idle", frozenset())
    problems += _missing_fields(
        content, "text_enrichers", TEXT_ENRICHER_CONFIG_TYPES, "text_enrichers", frozenset()
    )
    assert not problems, "config.example.yaml is missing fields:\n" + "\n".join(problems)


def test_shared_filter_fields_are_documented_once():
    # _OutputFilterMixin fields are excluded from the per-type check above -
    # they're documented once, generically, in this section instead of
    # per-output-type (see config.example.yaml itself).
    content = CONFIG_EXAMPLE.read_text(encoding="utf-8")
    m = re.search(
        r"^  # -{5,}\s*\n  # Per-output content filters.*?\n  # -{5,}\s*\n"  # opening banner
        r"(.*?)"  # section body
        r"(?=^  # -{5,}\s*\n)",  # up to the next section's own opening banner
        content,
        re.M | re.S,
    )
    assert m, "the 'Per-output content filters' section header wasn't found at all"
    section = m.group(0)
    for name in sorted(config_schema._FILTER_FIELD_NAMES):
        assert re.search(rf"\b{re.escape(name)}\b", section), (
            f"{name} isn't mentioned in the shared content-filters section"
        )
