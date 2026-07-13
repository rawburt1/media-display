"""Tests for mediainfo.registries' lazy class resolution - registry values
are dotted import-path strings, resolved (and only imported) on first use.
"""

import importlib
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


# ---------------------------------------------------------------------------
# resolve() must skip a plugin whose own dependency isn't installed, not
# crash the whole registry lookup (N3 - see
# docs/architecture-usability-review-2026-07.md; missing dependencies must
# not crash the app, CLAUDE.md §2).
# ---------------------------------------------------------------------------


def test_resolve_returns_none_and_logs_when_the_module_cannot_be_imported(caplog):
    with patch(
        "mediainfo.registries.importlib.import_module",
        side_effect=ModuleNotFoundError("No module named 'pyatv'"),
    ):
        cls = registries.resolve("mediainfo.sources.appletv.AppleTvSource")

    assert cls is None
    assert "AppleTvSource" in caplog.text
    assert "pyatv" in caplog.text


def test_get_source_class_returns_none_when_its_dependency_is_missing():
    with patch(
        "mediainfo.registries.importlib.import_module",
        side_effect=ModuleNotFoundError("No module named 'pyatv'"),
    ):
        assert registries.get_source_class("appletv") is None


def test_get_output_class_returns_none_when_its_dependency_is_missing():
    with patch(
        "mediainfo.registries.importlib.import_module",
        side_effect=ModuleNotFoundError("No module named 'pychromecast'"),
    ):
        assert registries.get_output_class("nest_hub") is None


def test_build_sources_skips_a_source_with_a_missing_dependency_but_keeps_the_rest():
    from pathlib import Path

    from mediainfo import wiring
    from mediainfo.config import Config

    config = Config.load(Path(__file__).resolve().parents[1] / "config.example.yaml")
    config.priority = ["appletv", "kodi"]

    real_import_module = importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == "mediainfo.sources.appletv":
            raise ModuleNotFoundError("No module named 'pyatv'")
        return real_import_module(name, *args, **kwargs)

    with patch("mediainfo.registries.importlib.import_module", side_effect=fake_import):
        sources = wiring.build_sources(config)

    names = {s.name for s in sources}
    assert "appletv" not in names
    assert "kodi" in names
