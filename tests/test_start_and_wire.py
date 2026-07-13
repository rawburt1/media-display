"""Tests for mediainfo.__main__._start_and_wire and _Subsystems: the N7
(see docs/architecture-usability-review-2026-07.md) reuse-vs-rebuild glue
between compute_reload_plan()'s ReloadPlan and the actual source/enricher/
idle_source/mediadata_store/orchestrator objects.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mediainfo.__main__ import _Subsystems, _start_and_wire
from mediainfo.reload_plan import ReloadPlan


def _plan(**overrides) -> ReloadPlan:
    fields = dict(
        cache_dirty=False,
        sources_dirty=False,
        enrichers_dirty=False,
        text_enrichers_dirty=False,
        idle_dirty=False,
        mediadata_store_dirty=False,
        library_dirty=False,
        overrides_dirty=False,
        posters_dirty=False,
        history_dirty=False,
        orchestrator_dirty=False,
    )
    fields.update(overrides)
    return ReloadPlan(**fields)


_OLD_STORE = MagicMock(name="old-store")
_FRESH_STORE = MagicMock(name="fresh-store")


def _previous(orch=None) -> _Subsystems:
    return _Subsystems(
        orch=orch if orch is not None else MagicMock(name="previous-orch"),
        sources=["old-source"],
        enrichers=["old-enricher"],
        text_enrichers=["old-text-enricher"],
        idle_source="old-idle",
        mediadata_store=_OLD_STORE,
    )


def _patched_builders():
    return (
        patch("mediainfo.__main__.build_mediadata_store", return_value=_FRESH_STORE),
        patch("mediainfo.__main__.build_sources", return_value=["fresh-source"]),
        patch("mediainfo.__main__.build_enrichers", return_value=["fresh-enricher"]),
        patch("mediainfo.__main__.build_text_enrichers", return_value=["fresh-text-enricher"]),
        patch("mediainfo.__main__.build_idle_source", return_value="fresh-idle"),
        patch("mediainfo.__main__.start_orchestrator", return_value=MagicMock(name="fresh-orch")),
        patch("mediainfo.__main__.build_app_services", return_value=MagicMock()),
        patch("mediainfo.__main__.attach_services"),
    )


def test_first_boot_builds_everything_fresh():
    (
        p_mediadata,
        p_sources,
        p_enrichers,
        p_text_enrichers,
        p_idle,
        p_start_orch,
        p_app_services,
        p_attach,
    ) = _patched_builders()
    with p_mediadata, p_sources, p_enrichers, p_text_enrichers, p_idle, p_start_orch:
        state = _start_and_wire(MagicMock(), [], MagicMock(), MagicMock(), MagicMock())

    assert state.sources == ["fresh-source"]
    assert state.enrichers == ["fresh-enricher"]
    assert state.text_enrichers == ["fresh-text-enricher"]
    assert state.idle_source == "fresh-idle"
    assert state.mediadata_store is _FRESH_STORE


def test_reload_with_nothing_dirty_reuses_everything_and_never_touches_orchestrator():
    previous = _previous()
    plan = _plan()  # nothing dirty

    with (
        patch("mediainfo.__main__.build_sources") as build_sources,
        patch("mediainfo.__main__.build_enrichers") as build_enrichers,
        patch("mediainfo.__main__.build_text_enrichers") as build_text_enrichers,
        patch("mediainfo.__main__.build_idle_source") as build_idle_source,
        patch("mediainfo.__main__.build_mediadata_store") as build_mediadata_store,
        patch("mediainfo.__main__.start_orchestrator") as start_orch,
        patch("mediainfo.__main__.build_app_services", return_value=MagicMock()),
        patch("mediainfo.__main__.attach_services"),
    ):
        state = _start_and_wire(
            MagicMock(),
            [],
            MagicMock(),
            MagicMock(),
            MagicMock(),
            previous=previous,
            plan=plan,
        )

    build_sources.assert_not_called()
    build_enrichers.assert_not_called()
    build_text_enrichers.assert_not_called()
    build_idle_source.assert_not_called()
    build_mediadata_store.assert_not_called()
    start_orch.assert_not_called()
    previous.orch.stop.assert_not_called()
    previous.orch.join.assert_not_called()
    assert state.orch is previous.orch
    assert state.sources == ["old-source"]
    assert state.mediadata_store is _OLD_STORE


def test_reload_with_only_sources_dirty_rebuilds_sources_and_orchestrator_but_reuses_the_rest():
    previous = _previous()
    plan = _plan(sources_dirty=True, orchestrator_dirty=True)
    fresh_orch = MagicMock(name="fresh-orch")

    with (
        patch("mediainfo.__main__.build_sources", return_value=["fresh-source"]) as build_sources,
        patch("mediainfo.__main__.build_enrichers") as build_enrichers,
        patch("mediainfo.__main__.build_text_enrichers") as build_text_enrichers,
        patch("mediainfo.__main__.build_idle_source") as build_idle_source,
        patch("mediainfo.__main__.build_mediadata_store") as build_mediadata_store,
        patch("mediainfo.__main__.start_orchestrator", return_value=fresh_orch) as start_orch,
        patch("mediainfo.__main__.build_app_services", return_value=MagicMock()),
        patch("mediainfo.__main__.attach_services"),
    ):
        state = _start_and_wire(
            MagicMock(),
            [],
            MagicMock(),
            MagicMock(),
            MagicMock(),
            previous=previous,
            plan=plan,
        )

    build_sources.assert_called_once()
    build_enrichers.assert_not_called()
    build_text_enrichers.assert_not_called()
    build_idle_source.assert_not_called()
    build_mediadata_store.assert_not_called()
    previous.orch.stop.assert_called_once()
    previous.orch.join.assert_called_once()
    start_orch.assert_called_once()
    _, kwargs = start_orch.call_args
    assert kwargs["sources"] == ["fresh-source"]
    assert kwargs["enrichers"] == ["old-enricher"]
    assert kwargs["text_enrichers"] == ["old-text-enricher"]
    assert kwargs["idle_source"] == "old-idle"
    assert state.orch is fresh_orch


def test_reload_with_history_dirty_rebuilds_orchestrator_but_reuses_every_collaborator():
    # history isn't one of _start_and_wire's own build_* calls (main()
    # rebuilds it before calling in) - but plan.orchestrator_dirty must
    # still be True whenever history changes, since Orchestrator holds a
    # `history` reference directly (see mediainfo/reload_plan.py).
    previous = _previous()
    plan = _plan(history_dirty=True, orchestrator_dirty=True)

    with (
        patch("mediainfo.__main__.build_sources") as build_sources,
        patch("mediainfo.__main__.build_enrichers") as build_enrichers,
        patch("mediainfo.__main__.build_text_enrichers") as build_text_enrichers,
        patch("mediainfo.__main__.build_idle_source") as build_idle_source,
        patch("mediainfo.__main__.build_mediadata_store") as build_mediadata_store,
        patch("mediainfo.__main__.start_orchestrator", return_value=MagicMock()) as start_orch,
        patch("mediainfo.__main__.build_app_services", return_value=MagicMock()),
        patch("mediainfo.__main__.attach_services"),
    ):
        _start_and_wire(
            MagicMock(),
            [],
            MagicMock(),
            MagicMock(),
            MagicMock(),
            history=MagicMock(),
            previous=previous,
            plan=plan,
        )

    build_sources.assert_not_called()
    build_enrichers.assert_not_called()
    build_text_enrichers.assert_not_called()
    build_idle_source.assert_not_called()
    build_mediadata_store.assert_not_called()
    previous.orch.stop.assert_called_once()
    previous.orch.join.assert_called_once()
    _, kwargs = start_orch.call_args
    assert kwargs["sources"] == ["old-source"]
    assert kwargs["enrichers"] == ["old-enricher"]


def test_build_app_services_and_attach_services_always_run_even_when_nothing_is_dirty():
    previous = _previous()
    plan = _plan()

    with (
        patch("mediainfo.__main__.build_sources"),
        patch("mediainfo.__main__.build_enrichers"),
        patch("mediainfo.__main__.build_text_enrichers"),
        patch("mediainfo.__main__.build_idle_source"),
        patch("mediainfo.__main__.build_mediadata_store"),
        patch("mediainfo.__main__.start_orchestrator"),
        patch("mediainfo.__main__.build_app_services", return_value=MagicMock()) as app_services,
        patch("mediainfo.__main__.attach_services") as attach,
    ):
        _start_and_wire(
            MagicMock(),
            [],
            MagicMock(),
            MagicMock(),
            MagicMock(),
            previous=previous,
            plan=plan,
        )

    app_services.assert_called_once()
    attach.assert_called_once()
