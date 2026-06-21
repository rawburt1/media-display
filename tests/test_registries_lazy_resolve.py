"""Tests for mediainfo.registries' lazy class resolution - registry values
are dotted import-path strings, resolved (and only imported) on first use.
"""

from unittest.mock import patch

from mediainfo import registries


def test_resolve_imports_and_returns_the_class():
    cls = registries.resolve("mediainfo.sources.kodi.KodiSource")
    from mediainfo.sources.kodi import KodiSource

    assert cls is KodiSource


def test_get_source_class_resolves_real_registry_entries():
    cls = registries.get_source_class("kodi")
    from mediainfo.sources.kodi import KodiSource

    assert cls is KodiSource


def test_get_source_class_returns_none_for_unknown_name():
    assert registries.get_source_class("nonexistent") is None


def test_get_source_class_tolerates_a_pre_resolved_class_in_the_registry():
    class _FakeSource:
        pass

    with patch("mediainfo.registries.SOURCE_CLASSES", {"fake": _FakeSource}):
        assert registries.get_source_class("fake") is _FakeSource


def test_output_name_for_class_finds_the_registry_key():
    from mediainfo.outputs.web import WebOutput

    assert registries.output_name_for_class(WebOutput) == "web"


def test_output_name_for_class_returns_none_for_unregistered_class():
    class _NotAnOutput:
        pass

    assert registries.output_name_for_class(_NotAnOutput) is None


def test_enricher_name_for_class_finds_the_registry_key():
    from mediainfo.enrichers.wikipedia import WikipediaEnricher

    assert registries.enricher_name_for_class(WikipediaEnricher) == "wikipedia"


def test_all_source_registry_entries_resolve_without_error():
    for name in registries.SOURCE_CLASSES:
        assert registries.get_source_class(name) is not None


def test_all_output_registry_entries_resolve_without_error():
    for name in registries.OUTPUT_CLASSES:
        assert registries.get_output_class(name) is not None


def test_all_enricher_registry_entries_resolve_without_error():
    for name in registries.ENRICHER_CLASSES:
        assert registries.get_enricher_class(name) is not None


def test_all_idle_registry_entries_resolve_without_error():
    for name in registries.IDLE_CLASSES:
        assert registries.get_idle_class(name) is not None
