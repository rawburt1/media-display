"""Tests for the Fas 1 GUI-redesign backend model: ui_model.UiComponent/
UiPipeline/UiDashboard and their builder (ui_builder.py), plus the new
read-only /api/ui/* routes in config_ui.py. See
docs/gui-redesign-phase0-inventory.md for the overall plan.
"""

import shutil
from pathlib import Path

import pytest

from mediainfo.config import ConfigUiConfig
from mediainfo.outputs.config_schema import _build_schema
from mediainfo.outputs.config_ui import ConfigUiOutput
from mediainfo.outputs.ui_builder import build_components

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


@pytest.fixture(autouse=True)
def no_server(monkeypatch):
    monkeypatch.setattr("threading.Thread.start", lambda self: None)


def _output(config_path):
    return ConfigUiOutput(ConfigUiConfig(enabled=True, host="127.0.0.1", port=8094), config_path)


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    shutil.copy(EXAMPLE_CONFIG, path)
    return path


@pytest.fixture
def incomplete_config_path(tmp_path):
    """Same fixture idea as tests/test_config_ui.py's incomplete_config_path
    (kept file-local per this repo's no-conftest.py convention): blanks
    sources.kodi.host on an otherwise-enabled, otherwise-untouched Kodi
    source."""
    path = tmp_path / "config.yaml"
    text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    text = text.replace(
        "host: 192.168.1.21       # IP address of the machine running Kodi",
        'host: ""                 # IP address of the machine running Kodi',
    )
    path.write_text(text, encoding="utf-8")
    return path


def _components(config_path):
    return _output(config_path)._build_ui_components()


def _by_id(components, id_):
    return next(c for c in components if c.id == id_)


# ---------------------------------------------------------------------------
# build_components(): category/type mapping
# ---------------------------------------------------------------------------

def test_enabled_source_is_media_component(config_path):
    kodi = _by_id(_components(config_path), "sources.kodi")
    assert kodi.category == "media"
    assert kodi.component_type == "source"
    assert kodi.enabled is True
    assert kodi.status in ("enabled", "connected")


def test_disabled_source_has_disabled_status(config_path):
    # emby has no section at all in config.example.yaml (every source that
    # *is* listed there is enabled: true), so it falls back to its
    # (disabled) default.
    emby = _by_id(_components(config_path), "sources.emby")
    assert emby.enabled is False
    assert emby.status == "disabled"


def test_enabled_output_is_display_component(config_path):
    web = _by_id(_components(config_path), "outputs.web")
    assert web.category == "display"
    assert web.component_type == "output"
    assert web.enabled is True


def test_output_plumbing_types_are_excluded(config_path):
    ids = {c.id for c in _components(config_path)}
    assert "outputs.config" not in ids
    assert "outputs.themes" not in ids


def test_enricher_is_metadata_component(config_path):
    musicbrainz = _by_id(_components(config_path), "enrichers.musicbrainz")
    assert musicbrainz.category == "metadata"
    assert musicbrainz.component_type == "enricher"


def test_text_enricher_is_metadata_component(config_path):
    lrclib = _by_id(_components(config_path), "text_enrichers.lrclib")
    assert lrclib.category == "metadata"
    assert lrclib.component_type == "text_enricher"
    assert lrclib.supports_test is False


def test_theme_is_appearance_component(config_path):
    themes = _components(config_path)
    theme_ids = {c.id for c in themes if c.component_type == "theme"}
    assert "themes.vinyl" in theme_ids
    vinyl = _by_id(themes, "themes.vinyl")
    assert vinyl.category == "appearance"


def test_theme_disabled_when_its_host_output_is_disabled(config_path):
    # config.example.yaml has outputs.themes.enabled: false but
    # outputs.themes.themes.vinyl.enabled: true - a theme can't be "on" if
    # the output that would render it is off.
    vinyl = _by_id(_components(config_path), "themes.vinyl")
    assert vinyl.enabled is False


def test_idle_source_is_media_component_without_test_support(config_path):
    idle = _by_id(_components(config_path), "idle.local")
    assert idle.category == "media"
    assert idle.component_type == "idle_source"
    assert idle.supports_test is False


def test_mediadata_and_cache_are_library_components(config_path):
    components = _components(config_path)
    mediadata = _by_id(components, "mediadata")
    cache = _by_id(components, "cache")
    assert mediadata.category == "library"
    assert mediadata.component_type == "mediadata"
    assert cache.category == "library"


def test_flat_sections_without_enabled_field_are_unknown_status(config_path):
    cache = _by_id(_components(config_path), "cache")
    assert cache.status == "unknown"


def test_auth_and_logging_are_advanced_components(config_path):
    components = _components(config_path)
    assert _by_id(components, "auth").category == "advanced"
    assert _by_id(components, "logging").category == "advanced"


def test_alerts_is_health_component(config_path):
    assert _by_id(_components(config_path), "alerts").category == "health"


# ---------------------------------------------------------------------------
# Required-field / needs_configuration status
# ---------------------------------------------------------------------------

def test_enabled_component_missing_required_field_needs_configuration(incomplete_config_path):
    kodi = _by_id(_components(incomplete_config_path), "sources.kodi")
    assert kodi.status == "needs_configuration"
    assert kodi.configured is False
    assert any("host" in w for w in kodi.warnings)


def test_disabled_component_with_missing_fields_has_no_warning(config_path):
    # emby is not configured (enabled=False by default) and is missing its
    # required host/api_key - that must not surface as a warning, since
    # it's off by design (matches _compute_overview's existing semantics).
    emby = _by_id(_components(config_path), "sources.emby")
    assert emby.enabled is False
    assert emby.status == "disabled"
    assert emby.warnings == []


def test_secret_required_field_set_is_not_flagged_missing(config_path):
    # spotify.client_secret is required, secret, and set (to a placeholder)
    # in config.example.yaml - ConfigStore masks its *value* to "" (by
    # design), so "missing" must be computed from secrets_set, not value.
    spotify = _by_id(_components(config_path), "sources.spotify")
    assert spotify.status != "needs_configuration"
    assert spotify.configured is True


# ---------------------------------------------------------------------------
# Health mapping
# ---------------------------------------------------------------------------

def test_health_error_status_maps_to_component_error(config_path):
    out = _output(config_path)
    schema = _build_schema()
    values, secrets_set = out._store.get_values()
    output_instances, output_secrets_set = out._store.get_output_instances()
    health = {
        "sources": [{"name": "kodi", "status": "error", "last_error": "Could not connect"}],
        "outputs": [], "enrichers": [], "idle_sources": [],
    }
    components = build_components(
        schema, values, secrets_set, output_instances, output_secrets_set, {}, health
    )
    kodi = _by_id(components, "sources.kodi")
    assert kodi.status == "error"
    assert kodi.health == "error"
    assert "Could not connect" in kodi.warnings


# ---------------------------------------------------------------------------
# Secrets: never leak a raw value, across every built component
# ---------------------------------------------------------------------------

def test_no_component_leaks_a_secret_value(config_path):
    for c in _components(config_path):
        for f in c.essential_fields + c.advanced_fields:
            if f.secret:
                assert f.value == ""


def test_config_path_points_at_the_right_yaml_location(config_path):
    components = _components(config_path)
    assert _by_id(components, "sources.kodi").config_path == "sources.kodi"
    assert _by_id(components, "outputs.pixoo").config_path == "outputs.pixoo"
    assert _by_id(components, "enrichers.fanarttv").config_path == "enrichers.fanarttv"


# ---------------------------------------------------------------------------
# /api/ui/components, /api/ui/component/<id>
# ---------------------------------------------------------------------------

def test_api_ui_components_returns_a_list(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/ui/components").get_json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert {"id", "category", "component_type", "status", "essential_fields"} <= data[0].keys()


def test_api_ui_component_returns_the_matching_one(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/ui/component/sources.kodi").get_json()
    assert data["id"] == "sources.kodi"
    assert data["category"] == "media"


def test_api_ui_component_unknown_id_is_404(config_path):
    out = _output(config_path)
    resp = out.app.test_client().get("/api/ui/component/does.not.exist")
    assert resp.status_code == 404
    assert "error" in resp.get_json()


def test_api_ui_components_does_not_leak_secrets(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/ui/components").get_json()
    for c in data:
        for f in c["essential_fields"] + c["advanced_fields"]:
            if f["secret"]:
                assert f["value"] == ""


# ---------------------------------------------------------------------------
# /api/ui/pipelines
# ---------------------------------------------------------------------------

def test_api_ui_pipelines_returns_one_default_pipeline(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/ui/pipelines").get_json()
    assert len(data) == 1
    assert data[0]["id"] == "default"


def test_pipeline_buckets_only_enabled_components(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/ui/pipelines").get_json()[0]
    assert "sources.kodi" in data["media_component_ids"]
    assert "sources.emby" not in data["media_component_ids"]
    assert "outputs.web" in data["display_component_ids"]
    assert "outputs.config" not in data["display_component_ids"]
    assert "outputs.themes" not in data["display_component_ids"]


def test_pipeline_with_no_enabled_sources_is_empty_not_broken(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("poll_interval_seconds: 5\n", encoding="utf-8")
    out = _output(path)
    data = out.app.test_client().get("/api/ui/pipelines").get_json()[0]
    assert data["media_component_ids"] == []
    assert data["display_component_ids"] == []


# ---------------------------------------------------------------------------
# /api/ui/dashboard
# ---------------------------------------------------------------------------

def test_api_ui_dashboard_returns_expected_shape(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/ui/dashboard").get_json()
    assert "now_playing" in data
    assert "restart_required" in data
    assert data["pipeline"]["id"] == "default"
    assert "health" in data and "counts_by_status" in data["health"]


def test_api_ui_dashboard_has_no_warnings_for_intentionally_disabled_components(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/ui/dashboard").get_json()
    assert data["health"]["warnings"] == []


def test_api_ui_dashboard_surfaces_needs_configuration_warning(incomplete_config_path):
    out = _output(incomplete_config_path)
    data = out.app.test_client().get("/api/ui/dashboard").get_json()
    assert any("host" in w for w in data["health"]["warnings"])


def test_api_ui_dashboard_works_without_currently_playing_data(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/ui/dashboard").get_json()
    assert data["now_playing"] is None
    assert data["active_source"] is None
