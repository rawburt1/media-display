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

The second half below (H3 in docs/architecture-usability-review-2026-07.md)
goes further: every plugin class self-declares its own `name` and
`config_class` (see e.g. MediaSource.name/config_class), independent of
mediainfo/registries.py's own dotted-path dicts. Deliberately NOT used to
*build* the registries - registries.py's lazy dotted-path resolution
(only importing a plugin module when it's actually referenced) is kept as
the real runtime source of truth, per that review's own recommendation.
Instead, these tests resolve every registered class once (test-time only,
no production startup cost) and cross-check its self-declared name/
config_class against the registry key/entry it's filed under - catching a
copy-paste class-attribute typo or a registry key that quietly points at
the wrong class, which the key-set-only checks above can't see.
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


# ---------------------------------------------------------------------------
# Self-declared name/config_class vs. the registry they're filed under
# (H3 - the 5 plugin families with a *_CONFIG_TYPES dict: sources, outputs,
# enrichers, text_enrichers, idle. Themes are a nested plugin type inside
# outputs.themes, not one of these 5, and aren't covered here.)
# ---------------------------------------------------------------------------


def _assert_self_declaration_matches_registry(
    family: str, class_registry: dict, config_registry: dict
) -> None:
    for key, entry in class_registry.items():
        cls = registries._resolve_entry(entry)
        assert cls is not None, f"{family}[{key!r}] ({entry}) failed to resolve"
        assert cls.name == key, (
            f"{family}[{key!r}]: {cls.__module__}.{cls.__qualname__}.name is "
            f"{cls.name!r}, expected {key!r} - registry key and the class's own "
            f"self-declared name have drifted apart"
        )
        assert cls.config_class is config_registry[key], (
            f"{family}[{key!r}]: {cls.__module__}.{cls.__qualname__}.config_class is "
            f"{cls.config_class!r}, expected {config_registry[key]!r} - the class's "
            f"self-declared config_class doesn't match what it's actually configured "
            f"with in mediainfo.config"
        )


def test_source_classes_self_declare_name_and_config_class():
    _assert_self_declaration_matches_registry(
        "sources", registries.SOURCE_CLASSES, SOURCE_CONFIG_TYPES
    )


def test_output_classes_self_declare_name_and_config_class():
    _assert_self_declaration_matches_registry(
        "outputs", registries.OUTPUT_CLASSES, OUTPUT_CONFIG_TYPES
    )


def test_enricher_classes_self_declare_name_and_config_class():
    _assert_self_declaration_matches_registry(
        "enrichers", registries.ENRICHER_CLASSES, ENRICHER_CONFIG_TYPES
    )


def test_text_enricher_classes_self_declare_name_and_config_class():
    _assert_self_declaration_matches_registry(
        "text_enrichers", registries.TEXT_ENRICHER_CLASSES, TEXT_ENRICHER_CONFIG_TYPES
    )


def test_idle_classes_self_declare_name_and_config_class():
    _assert_self_declaration_matches_registry("idle", registries.IDLE_CLASSES, IDLE_CONFIG_TYPES)
