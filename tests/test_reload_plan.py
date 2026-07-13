"""Tests for mediainfo.reload_plan.compute_reload_plan (N7 - see
docs/architecture-usability-review-2026-07.md): which subsystems a
config-file hot-reload needs to rebuild vs can leave running untouched.

Uses a real Config.from_dict({}) baseline (every field has a default) and
dataclasses.replace() to vary exactly one field at a time, so equality
comparisons are real structural comparisons - not MagicMock identity
tricks - matching how compute_reload_plan is actually used in production.
"""

from __future__ import annotations

import dataclasses

import pytest

from mediainfo.config import Config
from mediainfo.reload_plan import compute_reload_plan


@pytest.fixture
def base_config() -> Config:
    return Config.from_dict({})


def _all_dirty_fields(plan) -> set[str]:
    return {f.name for f in dataclasses.fields(plan) if getattr(plan, f.name)}


# ---------------------------------------------------------------------------
# No-op reload
# ---------------------------------------------------------------------------


def test_nothing_changed_nothing_is_dirty(base_config):
    plan = compute_reload_plan(base_config, base_config)
    assert _all_dirty_fields(plan) == set()


def test_equal_but_distinct_config_objects_are_not_dirty(base_config):
    # dataclasses.replace() with no changes returns a new, equal object -
    # confirms this is a real structural comparison, not identity.
    new_config = dataclasses.replace(base_config)
    assert new_config is not base_config
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == set()


# ---------------------------------------------------------------------------
# Direct, single-subsystem changes
# ---------------------------------------------------------------------------


def test_sources_change_only_dirties_sources_and_orchestrator(base_config):
    new_config = dataclasses.replace(base_config, sources={"kodi": "x"})
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == {"sources_dirty", "orchestrator_dirty"}


def test_priority_change_dirties_sources_like_a_sources_change(base_config):
    new_config = dataclasses.replace(base_config, priority=["kodi", "plex"])
    plan = compute_reload_plan(base_config, new_config)
    assert plan.sources_dirty
    assert plan.orchestrator_dirty


def test_library_change_dirties_enrichers_and_idle_too(base_config):
    new_config = dataclasses.replace(
        base_config, library=dataclasses.replace(base_config.library, max_age_days=999)
    )
    plan = compute_reload_plan(base_config, new_config)
    # build_enrichers()/build_idle_source() both take `library` - a
    # rebuilt MusicLibrary means any library-capability enricher/idle
    # source built against the old one would hold a stale reference.
    assert _all_dirty_fields(plan) == {
        "library_dirty",
        "enrichers_dirty",
        "idle_dirty",
        "orchestrator_dirty",
    }


def test_overrides_change_dirties_only_overrides_and_orchestrator(base_config):
    new_config = dataclasses.replace(
        base_config, overrides=dataclasses.replace(base_config.overrides, enabled=False)
    )
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == {"overrides_dirty", "orchestrator_dirty"}


def test_posters_change_dirties_only_posters_and_orchestrator(base_config):
    new_config = dataclasses.replace(
        base_config, posters=dataclasses.replace(base_config.posters, enabled=False)
    )
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == {"posters_dirty", "orchestrator_dirty"}


def test_history_change_dirties_only_history_and_orchestrator(base_config):
    new_config = dataclasses.replace(
        base_config, history=dataclasses.replace(base_config.history, enabled=False)
    )
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == {"history_dirty", "orchestrator_dirty"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("poll_interval_seconds", 99),
        ("rotation_interval_seconds", 99),
        ("backoff_initial_seconds", 99),
        ("backoff_max_seconds", 999),
        ("nothing_playing_grace_seconds", 99),
        ("enrichment_deadline_seconds", 99),
    ],
)
def test_orchestrator_scalar_change_dirties_only_orchestrator(base_config, field, value):
    new_config = dataclasses.replace(base_config, **{field: value})
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == {"orchestrator_dirty"}


def test_alerts_change_dirties_only_orchestrator(base_config):
    new_config = dataclasses.replace(
        base_config, alerts=dataclasses.replace(base_config.alerts, enabled=True)
    )
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == {"orchestrator_dirty"}


# ---------------------------------------------------------------------------
# Cache: the widest-reaching dependency (feeds mediadata_store, enrichers,
# text_enrichers, and the orchestrator directly)
# ---------------------------------------------------------------------------


def test_cache_change_dirties_every_downstream_subsystem(base_config):
    new_config = dataclasses.replace(
        base_config, cache=dataclasses.replace(base_config.cache, dir="/tmp/somewhere-else")
    )
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == {
        "cache_dirty",
        "mediadata_store_dirty",
        "enrichers_dirty",
        "text_enrichers_dirty",
        "orchestrator_dirty",
    }


# ---------------------------------------------------------------------------
# mediadata / enrichers / text_enrichers: mediadata_store's real dependencies
# ---------------------------------------------------------------------------


def test_mediadata_change_dirties_mediadata_store_and_its_consumers(base_config):
    new_config = dataclasses.replace(
        base_config, mediadata=dataclasses.replace(base_config.mediadata, path="/tmp/elsewhere")
    )
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == {
        "mediadata_store_dirty",
        "enrichers_dirty",
        "text_enrichers_dirty",
        "orchestrator_dirty",
    }


def test_enrichers_change_dirties_mediadata_store_and_text_enrichers_too(base_config):
    new_config = dataclasses.replace(base_config, enrichers={"tmdb": "x"})
    plan = compute_reload_plan(base_config, new_config)
    # build_mediadata_store() reads credentials out of config.enrichers
    # (discogs/tmdb/fanarttv/lastfm) and whether enrichers.mediadata is
    # enabled - any enrichers change could affect it.
    assert _all_dirty_fields(plan) == {
        "enrichers_dirty",
        "mediadata_store_dirty",
        "text_enrichers_dirty",
        "orchestrator_dirty",
    }


def test_text_enrichers_change_dirties_mediadata_store_and_enrichers_too(base_config):
    new_config = dataclasses.replace(base_config, text_enrichers={"lrclib": "x"})
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == {
        "text_enrichers_dirty",
        "mediadata_store_dirty",
        "enrichers_dirty",
        "orchestrator_dirty",
    }


# ---------------------------------------------------------------------------
# idle: idle, idle_priority, idle_mode all feed build_idle_source()
# ---------------------------------------------------------------------------


def test_idle_change_dirties_only_idle_and_orchestrator(base_config):
    new_config = dataclasses.replace(base_config, idle={"pexels": "x"})
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == {"idle_dirty", "orchestrator_dirty"}


def test_idle_priority_change_dirties_idle_like_an_idle_change(base_config):
    new_config = dataclasses.replace(base_config, idle_priority=["pexels", "local"])
    plan = compute_reload_plan(base_config, new_config)
    assert plan.idle_dirty
    assert plan.orchestrator_dirty


def test_idle_mode_change_dirties_idle_like_an_idle_change(base_config):
    new_config = dataclasses.replace(base_config, idle_mode="random")
    plan = compute_reload_plan(base_config, new_config)
    assert plan.idle_dirty
    assert plan.orchestrator_dirty


# ---------------------------------------------------------------------------
# Fields the orchestrator genuinely doesn't care about
# ---------------------------------------------------------------------------


def test_outputs_change_is_not_in_the_plan_at_all(base_config):
    # Outputs are instantiated once at startup and never touched by the
    # reload loop's subsystem rebuilding (see _warn_output_changes) -
    # compute_reload_plan has no opinion on them.
    new_config = dataclasses.replace(base_config, outputs={"web": ["x"]})
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == set()


def test_logging_change_is_not_in_the_plan_at_all(base_config):
    new_config = dataclasses.replace(
        base_config, logging=dataclasses.replace(base_config.logging, level="DEBUG")
    )
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == set()


def test_auth_change_is_not_in_the_plan_at_all(base_config):
    # auth changes require a restart regardless (see config_ui.py's
    # _restart_required) - not something compute_reload_plan tracks.
    new_config = dataclasses.replace(
        base_config, auth=dataclasses.replace(base_config.auth, username="someone-else")
    )
    plan = compute_reload_plan(base_config, new_config)
    assert _all_dirty_fields(plan) == set()
