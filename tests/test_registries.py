"""Registry-completeness checks.

Every source/output/enricher/idle-source plugin needs a matching entry in
two places: a config dataclass registered in mediainfo/config/'s
`*_CONFIG_TYPES`, and an implementation class registered in
mediainfo/registries.py's `*_CLASSES`. A key present in one but not the
other doesn't fail loudly - it just makes that plugin silently show up as
"unknown" (if missing from *_CLASSES) or "not_configured" (if missing from
*_CONFIG_TYPES) instead of ever actually running. These tests catch that
mismatch at test time instead of someone noticing a plugin quietly doing
nothing in production.
"""

from mediainfo import registries
from mediainfo.config import (
    ENRICHER_CONFIG_TYPES,
    IDLE_CONFIG_TYPES,
    OUTPUT_CONFIG_TYPES,
    SOURCE_CONFIG_TYPES,
    TEXT_ENRICHER_CONFIG_TYPES,
    THEMES_CONFIG_TYPES,
)


def test_source_registries_have_matching_keys():
    assert set(SOURCE_CONFIG_TYPES) == set(registries.SOURCE_CLASSES)


def test_output_registries_have_matching_keys():
    assert set(OUTPUT_CONFIG_TYPES) == set(registries.OUTPUT_CLASSES)


def test_enricher_registries_have_matching_keys():
    assert set(ENRICHER_CONFIG_TYPES) == set(registries.ENRICHER_CLASSES)


def test_text_enricher_registries_have_matching_keys():
    assert set(TEXT_ENRICHER_CONFIG_TYPES) == set(registries.TEXT_ENRICHER_CLASSES)


def test_idle_registries_have_matching_keys():
    assert set(IDLE_CONFIG_TYPES) == set(registries.IDLE_CLASSES)


def test_theme_registries_have_matching_keys():
    assert set(THEMES_CONFIG_TYPES) == set(registries.THEME_CLASSES)
