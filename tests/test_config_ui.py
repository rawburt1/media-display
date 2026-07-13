"""Tests for the config output (web UI for editing config.yaml)."""

import asyncio
import os
import shutil
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask
from flask.testing import FlaskClient

from mediainfo.config import AutoRotatePresetConfig, Config, ConfigUiConfig
from mediainfo.config.outputs import parse_presets
from mediainfo.config_backup import backup_config_file, list_backups
from mediainfo.outputs.config_ui import ConfigUiOutput, _restart_process

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


class _CsrfExemptClient(FlaskClient):
    """Every mutating route now requires the same header the real UI's own
    JS always sends (see mediainfo/web_auth.py's _require_csrf_header) -
    inject it automatically here rather than touching every .post()/
    .delete() call site in this file."""

    def open(self, *args, **kwargs):
        headers = kwargs.setdefault("headers", {})
        if isinstance(headers, dict):
            headers.setdefault("X-Requested-With", "XMLHttpRequest")
        return super().open(*args, **kwargs)


@pytest.fixture(autouse=True)
def csrf_exempt_test_client(monkeypatch):
    # Patched on the Flask class itself (not just one instance) so every
    # ConfigUiOutput built in this file - however it's constructed - picks
    # this up, not just the ones going through the _output() helper below.
    monkeypatch.setattr(Flask, "test_client_class", _CsrfExemptClient)


@pytest.fixture(autouse=True)
def no_server(monkeypatch):
    monkeypatch.setattr("threading.Thread.start", lambda self: None)


@pytest.fixture(autouse=True)
def fake_appletv_async(monkeypatch):
    # Thread.start() above is a no-op, so the real background loop+thread
    # created per pairing attempt never actually runs. Run coroutines
    # directly instead, and skip tearing down the (never-started) thread.
    monkeypatch.setattr(
        ConfigUiOutput,
        "_run_appletv_async",
        staticmethod(lambda loop, coro, timeout=30: asyncio.run(coro)),
    )
    monkeypatch.setattr(
        ConfigUiOutput, "_stop_appletv_loop", staticmethod(lambda loop, thread: None)
    )


def _config(**kwargs):
    return ConfigUiConfig(enabled=True, **kwargs)


def _output(config_path):
    return ConfigUiOutput(_config(), config_path)


def _client(out, url_prefix=""):
    """Register out's blueprint on a throwaway local Flask app and return
    a test client against it - see tests/test_nest_hub.py for the harness
    pattern (H1, see docs/architecture-usability-review-2026-07.md). Built
    as Flask("mediainfo.outputs.config_ui") so templates/ and the
    blueprint's own static_folder resolve - see tests/test_feeds.py for
    why. The csrf_exempt_test_client fixture above patches Flask.test_client_class
    globally, so this fresh app picks it up too.
    """
    # static_folder=None: matches the real SharedHttpServer - see its own
    # comment for why (the app-level default static route would shadow
    # config_ui's own blueprint-scoped one at the same URL pattern).
    app = Flask("mediainfo.outputs.config_ui", static_folder=None)
    app.register_blueprint(out.build_http_blueprint(url_prefix), url_prefix=url_prefix or None)
    return app.test_client()


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    shutil.copy(EXAMPLE_CONFIG, path)
    return path


@pytest.fixture
def library_config_path(tmp_path):
    """Like config_path, but with library.db_path redirected into
    tmp_path - otherwise the config UI's library browser would open
    (and create) ./library/library.db relative to the test runner's CWD.
    """
    path = tmp_path / "config.yaml"
    text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    text = text.replace("db_path: ./library/library.db", f"db_path: {tmp_path / 'library.db'}")
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def incomplete_config_path(tmp_path):
    """Like config_path, but blanks out sources.kodi.host - a field
    _REQUIRED_FIELDS (config_schema.py) marks required - while leaving the
    source enabled and its other fields (including the secret
    sources.kodi.password) untouched. Exercises the "enabled but missing a
    required field" case: the Overview page's "missing required settings"
    warning is computed client-side from /api/schema + /api/config (see
    ConfigUiOutput._compute_overview's docstring), so what must hold at the
    API layer is that /api/schema still marks the field required and
    /api/config still reports it empty without leaking unrelated secrets.
    """
    path = tmp_path / "config.yaml"
    text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    text = text.replace(
        "host: 192.168.1.21       # IP address of the machine running Kodi",
        'host: ""                 # IP address of the machine running Kodi',
    )
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# /api/schema
# ---------------------------------------------------------------------------


def test_schema_includes_all_categories(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    # One key per _FLAT_SECTIONS entry (cache/history/library/overrides/
    # posters/alerts/auth/logging/mediadata), the four per-type-registry
    # categories, "themes" (the individual Display Theme plugins nested
    # inside a "themes" output instance - see mediainfo/config/themes.py),
    # "auto_rotate" (AutoRotateConfig's own enabled/interval_seconds
    # scalar fields - presets itself is bespoke UI, not schema-driven),
    # plus filter_meta/auto_rotate_meta and the presentation-metadata keys
    # the guided UI needs (flat_sections/type_info/category_info/
    # enricher_groups).
    assert set(data.keys()) == {
        "general",
        "cache",
        "history",
        "library",
        "overrides",
        "posters",
        "alerts",
        "auth",
        "logging",
        "mediadata",
        "sources",
        "outputs",
        "enrichers",
        "idle",
        "themes",
        "auto_rotate",
        "filter_meta",
        "auto_rotate_meta",
        "flat_sections",
        "type_info",
        "category_info",
        "enricher_groups",
    }


def test_schema_mediadata_section_has_its_two_scalar_fields(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    field_names = {f["name"] for f in data["mediadata"]}
    assert field_names == {"path", "cache_first"}


def test_form_saves_history_section(config_path):
    out = _output(config_path)
    client = _client(out)
    client.post("/api/config/form", json={"values": {"history.max_entries": 500}})
    saved = config_path.read_text()
    assert "max_entries: 500" in saved


def test_schema_includes_known_source_types(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    assert "kodi" in data["sources"]
    assert "plex" in data["sources"]


def test_schema_includes_simple_list_fields(config_path):
    # speaker_ips/blacklist are flat lists of strings - simple enough to
    # edit as a one-item-per-line text box in the form.
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    fields = {f["name"]: f for f in data["sources"]["sonos"]}
    assert fields["blacklist"]["type"] == "list"
    assert fields["blacklist"]["default"] == []
    assert fields["speaker_ips"]["type"] == "list"
    assert "enabled" in fields


def test_schema_marks_screen_off_hours_with_time_range_widget(config_path):
    # The new shell's client-side time-range editor (two <input type="time">
    # + Clear) keys off this widget marker - see components.js's
    # renderTimeRangeField().
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    field = next(f for f in data["outputs"]["pixoo"] if f["name"] == "screen_off_hours")
    assert field["widget"] == "time_range"


def test_schema_marks_known_value_list_fields_with_choices(config_path):
    # transition_exclude is a simple list field with a fixed, known set of
    # valid values - exposed as `choices` so the UI can render a
    # toggle-button picker instead of a freeform one-item-per-line box.
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    field = next(f for f in data["outputs"]["web"] if f["name"] == "transition_exclude")
    assert field["choices"] == ["fade", "slide-left", "slide-right", "slide-up", "slide-down", "zoom"]


def test_schema_list_fields_without_known_values_have_no_choices(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    field = next(f for f in data["sources"]["sonos"] if f["name"] == "speaker_ips")
    assert "choices" not in field


def test_schema_excludes_complex_list_typed_fields(config_path):
    # `transforms` is a list of differently-shaped objects, not a flat
    # list of strings - excluded from the form, only editable via the
    # page's "Advanced" raw YAML editor.
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    field_names = {f["name"] for f in data["outputs"]["pixoo"]}
    assert "transforms" not in field_names
    assert "ip" in field_names


def test_schema_marks_secret_fields(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    fields = {f["name"]: f for f in data["enrichers"]["fanarttv"]}
    assert fields["api_key"]["secret"] is True


def test_schema_does_not_mark_host_as_secret(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    fields = {f["name"]: f for f in data["sources"]["kodi"]}
    assert fields["host"]["secret"] is False


# ---------------------------------------------------------------------------
# Required-field contract: /api/schema's "required" flag and /api/config's
# reporting of an enabled-but-incomplete component are what the Overview
# page's client-side "missing required settings" warning relies on.
# ---------------------------------------------------------------------------


def test_schema_marks_kodi_host_as_required(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    fields = {f["name"]: f for f in data["sources"]["kodi"]}
    assert fields["host"]["required"] is True


def test_schema_does_not_mark_non_required_field_as_required(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    fields = {f["name"]: f for f in data["sources"]["kodi"]}
    assert fields["port"]["required"] is False


def test_get_config_reports_empty_value_for_missing_required_field(
    incomplete_config_path,
):
    out = _output(incomplete_config_path)
    data = _client(out).get("/api/config").get_json()
    assert data["values"]["sources.kodi.enabled"] is True
    assert data["values"]["sources.kodi.host"] == ""


def test_get_config_does_not_leak_secrets_when_a_sibling_field_is_missing(
    incomplete_config_path,
):
    out = _output(incomplete_config_path)
    data = _client(out).get("/api/config").get_json()
    # kodi.password is still set in this fixture (only host was blanked) -
    # it must stay reported as set-but-masked, never as a raw value.
    assert data["secrets_set"]["sources.kodi.password"] is True
    assert data["values"]["sources.kodi.password"] == ""


# ---------------------------------------------------------------------------
# /api/config (GET)
# ---------------------------------------------------------------------------


def test_get_config_returns_current_values(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/config").get_json()
    assert data["values"]["sources.kodi.host"] == "192.168.1.21"
    assert data["values"]["general.poll_interval_seconds"] == 5


def test_get_config_returns_raw_yaml(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/config").get_json()
    assert "sources:" in data["raw_yaml"]


def test_get_config_uses_defaults_for_unconfigured_type(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/config").get_json()
    # discogs is not present in config.example.yaml
    assert data["values"]["enrichers.discogs.enabled"] is False


# ---------------------------------------------------------------------------
# /api/config (GET): outputs (multi-instance)
# ---------------------------------------------------------------------------


def test_get_config_outputs_single_instance_as_list_of_one(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/config").get_json()
    assert len(data["outputs"]["web"]) == 1
    assert data["outputs"]["web"][0]["enabled"] is True


def test_get_config_outputs_multiple_instances(config_path):
    config_path.write_text(
        """
outputs:
  ulanzi:
    - enabled: true
      device_ip: 1.1.1.1
    - enabled: true
      device_ip: 2.2.2.2
"""
    )
    out = _output(config_path)
    data = _client(out).get("/api/config").get_json()
    ips = [inst["device_ip"] for inst in data["outputs"]["ulanzi"]]
    assert ips == ["1.1.1.1", "2.2.2.2"]


def test_get_config_outputs_unconfigured_type_has_one_default_instance(config_path):
    config_path.write_text("poll_interval_seconds: 5\n")  # no outputs section at all
    out = _output(config_path)
    data = _client(out).get("/api/config").get_json()
    assert len(data["outputs"]["web"]) == 1
    assert data["outputs"]["web"][0]["enabled"] is False  # default


def test_get_config_themes_output_includes_its_nested_themes_dict(config_path):
    # ThemesConfig.themes is a raw dict (unlike ordinary scalar fields) -
    # excluded from _scalar_fields() like `transforms` elsewhere, but the
    # themes picker UI needs it round-tripped, unlike transforms (which
    # stays YAML-only) - see config_store.py's get_output_instances().
    config_path.write_text(
        """
outputs:
  themes:
    enabled: true
    port: 8097
    themes:
      color_palette:
        enabled: true
        swatch_count: 3
"""
    )
    out = _output(config_path)
    data = _client(out).get("/api/config").get_json()
    assert data["outputs"]["themes"][0]["themes"] == {
        "color_palette": {"enabled": True, "swatch_count": 3},
    }


def test_get_config_themes_output_defaults_to_empty_dict(config_path):
    config_path.write_text("outputs:\n  themes:\n    enabled: true\n")
    out = _output(config_path)
    data = _client(out).get("/api/config").get_json()
    assert data["outputs"]["themes"][0]["themes"] == {}


def test_get_config_themes_output_includes_its_nested_auto_rotate_dict(config_path):
    # auto_rotate.presets can hold either shape (a plain list of theme
    # names, or {"themes": [...], "when": [...]}) - same raw pass-through
    # as `themes` above, both verbatim, unvalidated (parse_presets() does
    # that at actual app startup).
    config_path.write_text(
        """
outputs:
  themes:
    enabled: true
    port: 8097
    auto_rotate:
      enabled: true
      interval_seconds: 20
      presets:
        minimal:
        - color_palette
        music:
          themes:
          - vinyl
          when:
          - music
"""
    )
    out = _output(config_path)
    data = _client(out).get("/api/config").get_json()
    assert data["outputs"]["themes"][0]["auto_rotate"] == {
        "enabled": True,
        "interval_seconds": 20,
        "presets": {
            "minimal": ["color_palette"],
            "music": {"themes": ["vinyl"], "when": ["music"]},
        },
    }


def test_other_output_types_do_not_get_a_themes_key(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/config").get_json()
    assert "themes" not in data["outputs"]["web"][0]


# ---------------------------------------------------------------------------
# Hidden types (hide/unhide individual sources/outputs/enrichers cards)
# ---------------------------------------------------------------------------


def test_get_config_hidden_types_empty_by_default(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/config").get_json()
    assert data["hidden_types"] == {"sources": [], "outputs": [], "enrichers": []}


def test_hide_type_adds_it_to_hidden_types(config_path):
    out = _output(config_path)
    client = _client(out)

    resp = client.post(
        "/api/config/hidden-types",
        json={"category": "sources", "name": "sonos", "hidden": True},
    )

    assert resp.get_json() == {
        "ok": True,
        "hidden_types": {"sources": ["sonos"], "outputs": [], "enrichers": []},
    }
    assert client.get("/api/config").get_json()["hidden_types"]["sources"] == ["sonos"]


def test_unhide_type_removes_it_from_hidden_types(config_path):
    out = _output(config_path)
    client = _client(out)
    client.post(
        "/api/config/hidden-types",
        json={"category": "sources", "name": "sonos", "hidden": True},
    )

    resp = client.post(
        "/api/config/hidden-types",
        json={"category": "sources", "name": "sonos", "hidden": False},
    )

    assert resp.get_json() == {
        "ok": True,
        "hidden_types": {"sources": [], "outputs": [], "enrichers": []},
    }


def test_hide_type_persists_across_instances(config_path):
    out1 = _output(config_path)
    _client(out1).post(
        "/api/config/hidden-types",
        json={"category": "enrichers", "name": "discogs", "hidden": True},
    )

    out2 = _output(config_path)
    data = _client(out2).get("/api/config").get_json()
    assert data["hidden_types"]["enrichers"] == ["discogs"]


def test_hide_type_does_not_require_restart(config_path):
    out = _output(config_path)
    client = _client(out)

    client.post(
        "/api/config/hidden-types",
        json={"category": "outputs", "name": "pixoo64", "hidden": True},
    )

    assert client.get("/api/overview").get_json()["restart_required"] is False


def test_hide_type_rejects_unknown_category(config_path):
    out = _output(config_path)
    client = _client(out)

    resp = client.post(
        "/api/config/hidden-types",
        json={"category": "idle", "name": "clock", "hidden": True},
    )

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_hide_type_rejects_missing_name(config_path):
    out = _output(config_path)
    client = _client(out)

    resp = client.post("/api/config/hidden-types", json={"category": "sources", "hidden": True})

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_hiding_same_type_twice_is_a_noop(config_path):
    out = _output(config_path)
    client = _client(out)
    client.post(
        "/api/config/hidden-types",
        json={"category": "sources", "name": "sonos", "hidden": True},
    )

    resp = client.post(
        "/api/config/hidden-types",
        json={"category": "sources", "name": "sonos", "hidden": True},
    )

    assert resp.get_json()["hidden_types"]["sources"] == ["sonos"]


def test_hidden_types_written_under_ui_hidden_types_key(config_path):
    out = _output(config_path)
    _client(out).post(
        "/api/config/hidden-types",
        json={"category": "sources", "name": "sonos", "hidden": True},
    )

    text = config_path.read_text()
    assert "ui_hidden_types:" in text
    # Config.from_dict() ignores the unknown top-level key entirely - it's a
    # UI-only preference, so the rest of the config still loads unaffected.
    assert Config.load(config_path).auth is not None


# ---------------------------------------------------------------------------
# /api/config/form (POST)
# ---------------------------------------------------------------------------


def test_save_form_updates_value(config_path):
    out = _output(config_path)
    client = _client(out)
    resp = client.post("/api/config/form", json={"values": {"sources.kodi.host": "10.0.0.99"}})
    assert resp.get_json() == {"ok": True, "restart_required": False}

    cfg = Config.load(config_path)
    assert cfg.sources["kodi"].host == "10.0.0.99"


def test_save_form_updates_general_field(config_path):
    out = _output(config_path)
    client = _client(out)
    client.post("/api/config/form", json={"values": {"general.poll_interval_seconds": 42}})

    cfg = Config.load(config_path)
    assert cfg.poll_interval_seconds == 42


def test_save_form_requires_restart_for_auth_change(config_path):
    # Every Flask-based output's HTTP Basic Auth check is wired up once at
    # process startup (install_auth() closes over the AuthConfig instance
    # passed in then) - a changed password never reaches an already-running
    # server via the regular hot-reload, so this must be flagged just like
    # an `outputs` change is.
    out = _output(config_path)
    client = _client(out)
    resp = client.post("/api/config/form", json={"values": {"auth.password": "new-secret"}})

    assert resp.get_json() == {"ok": True, "restart_required": True}
    assert Config.load(config_path).auth.password == "new-secret"


def test_save_form_no_restart_required_when_auth_untouched(config_path):
    out = _output(config_path)
    client = _client(out)
    resp = client.post("/api/config/form", json={"values": {"sources.kodi.host": "10.0.0.1"}})

    assert resp.get_json() == {"ok": True, "restart_required": False}


def test_schema_includes_cache_section(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    field_names = {f["name"] for f in data["cache"]}
    assert "min_width" in field_names
    assert "min_height" in field_names
    assert "dir" in field_names


def test_get_values_includes_cache_fields(config_path):
    out = _output(config_path)
    values = _client(out).get("/api/config").get_json()["values"]
    assert values["cache.min_width"] == 640
    assert values["cache.min_height"] == 480


def test_save_form_updates_cache_min_width(config_path):
    out = _output(config_path)
    client = _client(out)
    client.post(
        "/api/config/form",
        json={"values": {"cache.min_width": 320, "cache.min_height": 240}},
    )

    cfg = Config.load(config_path)
    assert cfg.cache.min_width == 320
    assert cfg.cache.min_height == 240


def test_save_form_updates_cache_preserves_other_cache_fields(config_path):
    out = _output(config_path)
    client = _client(out)
    client.post("/api/config/form", json={"values": {"cache.min_width": 100}})

    cfg = Config.load(config_path)
    assert cfg.cache.min_width == 100
    assert cfg.cache.max_age_days == 30  # untouched, kept its existing value


def test_save_form_preserves_untouched_fields(config_path):
    out = _output(config_path)
    client = _client(out)
    client.post("/api/config/form", json={"values": {"sources.kodi.host": "10.0.0.99"}})

    cfg = Config.load(config_path)
    assert cfg.enrichers["fanarttv"].api_key == "YOUR_FANART_TV_API_KEY"
    assert cfg.sources["kodi"].port == 8080


def test_save_form_preserves_comments(config_path):
    out = _output(config_path)
    client = _client(out)
    client.post("/api/config/form", json={"values": {"sources.kodi.host": "10.0.0.99"}})

    text = config_path.read_text()
    assert "# Copy this file to config.yaml" in text


def test_save_form_sets_simple_list_field(config_path):
    out = _output(config_path)
    client = _client(out)
    client.post(
        "/api/config/form",
        json={"values": {"sources.sonos.speaker_ips": ["192.168.1.10", "192.168.1.11"]}},
    )

    cfg = Config.load(config_path)
    assert cfg.sources["sonos"].speaker_ips == ["192.168.1.10", "192.168.1.11"]


def test_get_values_returns_simple_list_field(config_path):
    out = _output(config_path)
    client = _client(out)
    client.post(
        "/api/config/form",
        json={"values": {"sources.sonos.blacklist": ["Bedroom"]}},
    )

    values = client.get("/api/config").get_json()["values"]
    assert values["sources.sonos.blacklist"] == ["Bedroom"]


def test_save_form_sets_bool_field(config_path):
    out = _output(config_path)
    client = _client(out)
    client.post("/api/config/form", json={"values": {"sources.plex.enabled": False}})

    cfg = Config.load(config_path)
    assert cfg.sources["plex"].enabled is False


def test_save_form_creates_new_section_for_unconfigured_type(config_path):
    out = _output(config_path)
    client = _client(out)
    resp = client.post(
        "/api/config/form",
        json={
            "values": {
                "enrichers.discogs.enabled": True,
                "enrichers.discogs.token": "abc123",
            }
        },
    )
    assert resp.get_json()["ok"] is True

    cfg = Config.load(config_path)
    assert cfg.enrichers["discogs"].enabled is True
    assert cfg.enrichers["discogs"].token == "abc123"


def test_save_form_sets_simple_list_field_on_output_instance(config_path):
    config_path.write_text(
        """
outputs:
  web:
    - enabled: true
      port: 8090
"""
    )
    out = _output(config_path)
    client = _client(out)
    client.post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "web": [
                    {
                        "enabled": True,
                        "port": 8090,
                        "transition_exclude": ["zoom", "fade"],
                    },
                ],
            },
        },
    )

    cfg = Config.load(config_path)
    assert cfg.outputs["web"][0].transition_exclude == ["zoom", "fade"]


def test_save_form_updates_existing_output_instances(config_path):
    config_path.write_text(
        """
outputs:
  ulanzi:
    - enabled: true
      device_ip: 1.1.1.1
    - enabled: true
      device_ip: 2.2.2.2
"""
    )
    out = _output(config_path)
    client = _client(out)
    client.post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "ulanzi": [
                    {
                        "enabled": True,
                        "device_ip": "9.9.9.9",
                        "app_name": "now_playing",
                    },
                    {
                        "enabled": True,
                        "device_ip": "2.2.2.2",
                        "app_name": "now_playing",
                    },
                ]
            },
        },
    )

    cfg = Config.load(config_path)
    ips = [c.device_ip for c in cfg.outputs["ulanzi"]]
    assert ips == ["9.9.9.9", "2.2.2.2"]


def test_save_form_appends_new_output_instance(config_path):
    config_path.write_text(
        """
outputs:
  ulanzi:
    - enabled: true
      device_ip: 1.1.1.1
      app_name: now_playing
"""
    )
    out = _output(config_path)
    client = _client(out)
    client.post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "ulanzi": [
                    {
                        "enabled": True,
                        "device_ip": "1.1.1.1",
                        "app_name": "now_playing",
                    },
                    {
                        "enabled": True,
                        "device_ip": "2.2.2.2",
                        "app_name": "now_playing_2",
                    },
                ]
            },
        },
    )

    cfg = Config.load(config_path)
    ips = [c.device_ip for c in cfg.outputs["ulanzi"]]
    assert ips == ["1.1.1.1", "2.2.2.2"]


def test_save_form_appended_instance_loads_correctly_despite_trailing_comment(
    config_path,
):
    # ruamel.yaml can render a newly-appended instance visually before a
    # comment that trails the original list (see module docstring) - this
    # confirms that's purely cosmetic and the data still loads correctly.
    config_path.write_text(
        """
outputs:
  ulanzi:
    - enabled: true
      device_ip: 1.1.1.1
      app_name: now_playing

  # A comment that originally trailed the ulanzi section.
  web:
    enabled: true
"""
    )
    out = _output(config_path)
    client = _client(out)
    resp = client.post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "ulanzi": [
                    {
                        "enabled": True,
                        "device_ip": "1.1.1.1",
                        "app_name": "now_playing",
                    },
                    {
                        "enabled": True,
                        "device_ip": "2.2.2.2",
                        "app_name": "now_playing_2",
                    },
                ]
            },
        },
    )
    assert resp.get_json() == {"ok": True, "restart_required": True}

    cfg = Config.load(config_path)
    ips = [c.device_ip for c in cfg.outputs["ulanzi"]]
    assert ips == ["1.1.1.1", "2.2.2.2"]
    assert cfg.outputs["web"][0].enabled is True


def test_save_form_removes_trailing_output_instance(config_path):
    config_path.write_text(
        """
outputs:
  ulanzi:
    - enabled: true
      device_ip: 1.1.1.1
      app_name: now_playing
    - enabled: true
      device_ip: 2.2.2.2
      app_name: now_playing_2
"""
    )
    out = _output(config_path)
    client = _client(out)
    client.post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "ulanzi": [{"enabled": True, "device_ip": "1.1.1.1", "app_name": "now_playing"}]
            },
        },
    )

    cfg = Config.load(config_path)
    assert len(cfg.outputs["ulanzi"]) == 1
    assert cfg.outputs["ulanzi"][0].device_ip == "1.1.1.1"


def test_save_form_preserves_transforms_on_existing_output_instance(config_path):
    config_path.write_text(
        """
outputs:
  pixoo:
    - enabled: true
      ip: 1.1.1.1
      transforms:
        - fit: {width: 64, height: 64}
"""
    )
    out = _output(config_path)
    client = _client(out)
    client.post(
        "/api/config/form",
        json={"values": {}, "outputs": {"pixoo": [{"enabled": True, "ip": "9.9.9.9"}]}},
    )

    text = config_path.read_text()
    assert "transforms" in text
    assert "fit" in text
    cfg = Config.load(config_path)
    assert cfg.outputs["pixoo"][0].ip == "9.9.9.9"
    assert cfg.outputs["pixoo"][0].transforms == [{"fit": {"width": 64, "height": 64}}]


def test_save_form_round_trips_themes_dict_on_existing_output_instance(config_path):
    config_path.write_text(
        """
outputs:
  themes:
    - enabled: true
      port: 8097
      themes:
        color_palette:
          enabled: true
          swatch_count: 3
"""
    )
    out = _output(config_path)
    client = _client(out)
    # Mirrors what the browser actually posts: the full outputsData.themes
    # entry (as returned by GET /api/config, then possibly edited) - not
    # just the changed field, matching saveAll()'s Object.assign-free
    # whole-array-per-dirty-type post in app.html.
    get_data = client.get("/api/config").get_json()
    instance = get_data["outputs"]["themes"][0]
    instance["themes"]["color_palette"]["swatch_position"] = "top"

    client.post(
        "/api/config/form",
        json={"values": {}, "outputs": {"themes": [instance]}},
    )

    cfg = Config.load(config_path)
    assert cfg.outputs["themes"][0].themes == {
        "color_palette": {"enabled": True, "swatch_count": 3, "swatch_position": "top"},
    }


def test_save_form_round_trips_auto_rotate_on_existing_output_instance(config_path):
    config_path.write_text(
        """
outputs:
  themes:
    - enabled: true
      port: 8097
      auto_rotate:
        enabled: true
        interval_seconds: 20
        presets:
          minimal:
          - color_palette
          music:
            themes:
            - vinyl
            when: []
"""
    )
    out = _output(config_path)
    client = _client(out)
    get_data = client.get("/api/config").get_json()
    instance = get_data["outputs"]["themes"][0]
    instance["auto_rotate"]["presets"]["music"]["when"] = ["music"]

    client.post(
        "/api/config/form",
        json={"values": {}, "outputs": {"themes": [instance]}},
    )

    cfg = Config.load(config_path)
    presets = parse_presets(cfg.outputs["themes"][0].auto_rotate.presets)
    assert presets["music"] == AutoRotatePresetConfig(themes=["vinyl"], when=["music"])
    assert presets["minimal"] == AutoRotatePresetConfig(themes=["color_palette"], when=[])


def test_save_form_emptying_all_instances_results_in_empty_list(config_path):
    config_path.write_text(
        """
outputs:
  ulanzi:
    - enabled: true
      device_ip: 1.1.1.1
"""
    )
    out = _output(config_path)
    client = _client(out)
    client.post("/api/config/form", json={"values": {}, "outputs": {"ulanzi": []}})

    cfg = Config.load(config_path)
    assert cfg.outputs["ulanzi"] == []


def test_save_form_rejects_unknown_category(config_path):
    out = _output(config_path)
    client = _client(out)
    resp = client.post("/api/config/form", json={"values": {"bogus.kodi.host": "x"}})
    assert resp.get_json() == {
        "ok": True,
        "restart_required": False,
    }  # unknown keys are silently ignored, not an error

    cfg = Config.load(config_path)
    assert cfg.sources["kodi"].host == "192.168.1.21"  # unchanged


def test_save_form_empty_values_is_noop(config_path):
    out = _output(config_path)
    client = _client(out)
    resp = client.post("/api/config/form", json={"values": {}})
    assert resp.get_json() == {"ok": True, "restart_required": False}


# ---------------------------------------------------------------------------
# /api/config/raw (POST)
# ---------------------------------------------------------------------------


def test_save_raw_writes_valid_yaml(config_path):
    out = _output(config_path)
    client = _client(out)
    new_yaml = "poll_interval_seconds: 7\nrotation_interval_seconds: 30\npriority: []\n"
    resp = client.post("/api/config/raw", json={"yaml": new_yaml})
    # A raw save can change anything, including outputs - always flagged as
    # possibly needing a restart, rather than trying to diff what changed.
    assert resp.get_json() == {"ok": True, "restart_required": True}
    assert config_path.read_text() == new_yaml


def test_save_raw_rejects_invalid_yaml(config_path):
    out = _output(config_path)
    client = _client(out)
    original = config_path.read_text()
    resp = client.post("/api/config/raw", json={"yaml": "not: [valid"})
    data = resp.get_json()
    assert data["ok"] is False
    assert "error" in data
    assert config_path.read_text() == original  # unchanged on failure


def test_save_raw_rejects_malformed_source_section(config_path):
    out = _output(config_path)
    client = _client(out)
    original = config_path.read_text()
    # "sources.kodi" must be a mapping; a list breaks the `**values` expansion in Config.from_dict.
    resp = client.post(
        "/api/config/raw",
        json={"yaml": "sources:\n  kodi:\n    - enabled\n    - true\n"},
    )
    assert resp.get_json()["ok"] is False
    assert config_path.read_text() == original


# ---------------------------------------------------------------------------
# Config backups (list + restore from the UI)
# ---------------------------------------------------------------------------


def test_list_config_backups_empty_when_no_backups(config_path):
    out = _output(config_path)
    client = _client(out)
    resp = client.get("/api/config/backups")
    assert resp.get_json() == {"backups": []}


def test_list_config_backups_returns_entries_with_filename_and_mtime(config_path):
    backup_config_file(config_path)
    backup_config_file(config_path)
    out = _output(config_path)
    client = _client(out)

    resp = client.get("/api/config/backups")
    data = resp.get_json()

    expected_names = {b.name for b in list_backups(config_path)}
    assert {entry["filename"] for entry in data["backups"]} == expected_names
    assert all(isinstance(entry["mtime"], (int, float)) for entry in data["backups"])


def test_restore_backup_writes_backup_content_and_is_readable_via_config_load(
    config_path,
):
    original_text = config_path.read_text()
    backup_config_file(config_path)
    config_path.write_text("poll_interval_seconds: 999\npriority: []\n")

    out = _output(config_path)
    client = _client(out)
    filename = list_backups(config_path)[0].name

    resp = client.post("/api/config/backups/restore", json={"filename": filename})

    assert resp.get_json()["ok"] is True
    assert config_path.read_text() == original_text
    assert Config.load(config_path).auth is not None


def test_restore_backup_sets_restart_required(config_path):
    backup_config_file(config_path)
    config_path.write_text("poll_interval_seconds: 999\npriority: []\n")
    out = _output(config_path)
    client = _client(out)
    filename = list_backups(config_path)[0].name

    resp = client.post("/api/config/backups/restore", json={"filename": filename})

    assert resp.get_json()["restart_required"] is True


def test_restore_backup_rejects_unknown_filename(config_path):
    backup_config_file(config_path)
    original = config_path.read_text()
    out = _output(config_path)
    client = _client(out)

    resp = client.post("/api/config/backups/restore", json={"filename": "not-a-real-backup.bak"})

    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert "unknown backup" in data["error"].lower()
    assert config_path.read_text() == original


def test_restore_backup_errors_when_no_backups_exist(config_path):
    out = _output(config_path)
    client = _client(out)

    resp = client.post(
        "/api/config/backups/restore",
        json={"filename": "config.yaml.20260101T000000.bak"},
    )

    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert "no backups available" in data["error"].lower()


def test_restore_backup_missing_filename_returns_400(config_path):
    backup_config_file(config_path)
    out = _output(config_path)
    client = _client(out)

    resp = client.post("/api/config/backups/restore", json={})

    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert "no backup filename given" in data["error"].lower()


def test_restore_backup_itself_creates_a_new_undo_backup(config_path):
    backup_config_file(config_path)
    out = _output(config_path)
    client = _client(out)
    filename = list_backups(config_path)[0].name
    before_count = len(list_backups(config_path))

    client.post("/api/config/backups/restore", json={"filename": filename})

    assert len(list_backups(config_path)) == before_count + 1


def test_restore_backup_warns_but_still_restores_when_result_fails_to_validate(
    config_path,
):
    backup_config_file(config_path)  # backup of the valid example config
    backup_dir = config_path.parent / ".config_backups"
    broken = backup_dir / f"{config_path.name}.20200101T000000.bak"
    broken.write_text("not: [valid, yaml, at, all")

    out = _output(config_path)
    client = _client(out)

    resp = client.post("/api/config/backups/restore", json={"filename": broken.name})
    data = resp.get_json()

    assert data["ok"] is True
    assert "warning" in data
    assert config_path.read_text() == "not: [valid, yaml, at, all"


# ---------------------------------------------------------------------------
# /api/restart
# ---------------------------------------------------------------------------


@patch("mediainfo.outputs.config_ui.threading.Timer")
def test_restart_endpoint_schedules_restart_without_blocking(mock_timer_cls, config_path):
    out = _output(config_path)
    client = _client(out)

    resp = client.post("/api/restart")

    assert resp.get_json() == {"ok": True}
    mock_timer_cls.assert_called_once()
    args = mock_timer_cls.call_args.args
    assert args[1] is _restart_process
    mock_timer_cls.return_value.start.assert_called_once()


@patch("mediainfo.outputs.config_ui.os.kill")
def test_restart_process_sends_sigterm_to_self(mock_kill):
    _restart_process()

    mock_kill.assert_called_once_with(os.getpid(), signal.SIGTERM)


# ---------------------------------------------------------------------------
# /api/hitster-safe
# ---------------------------------------------------------------------------


def test_hitster_safe_status_defaults_to_disabled_when_unwired(config_path):
    out = _output(config_path)
    resp = _client(out).get("/api/hitster-safe")
    assert resp.get_json() == {"enabled": False}


def test_hitster_safe_status_reflects_get_handler(config_path):
    out = _output(config_path)
    out.set_hitster_safe_handlers(lambda: True, MagicMock())
    resp = _client(out).get("/api/hitster-safe")
    assert resp.get_json() == {"enabled": True}


def test_hitster_safe_toggle_calls_set_handler(config_path):
    out = _output(config_path)
    set_fn = MagicMock()
    out.set_hitster_safe_handlers(lambda: False, set_fn)

    resp = _client(out).post(
        "/api/hitster-safe",
        json={"enabled": True},
    )

    assert resp.get_json() == {"enabled": True}
    set_fn.assert_called_once_with(True)


def test_hitster_safe_toggle_unavailable_when_unwired(config_path):
    out = _output(config_path)
    resp = _client(out).post("/api/hitster-safe", json={"enabled": True})
    assert resp.status_code == 503


def test_hitster_safe_button_present_on_form_and_dashboard_pages(config_path):
    out = _output(config_path)
    client = _client(out)
    assert b"hitster-safe-btn" in client.get("/form").data
    assert b"hitster-safe-btn" in client.get("/dashboard").data


# ---------------------------------------------------------------------------
# attach() - see mediainfo.app_services.AppServices
# ---------------------------------------------------------------------------


def test_attach_wires_hitster_safe_overrides_and_health(config_path, tmp_path):
    from mediainfo.app_services import AppServices
    from mediainfo.artwork_overrides import ArtworkOverrideStore

    out = _output(config_path)

    def get_fn():
        return True

    set_fn = MagicMock()
    overrides = ArtworkOverrideStore(str(tmp_path / "overrides"))

    def health_provider():
        return {"status": "ok"}

    out.attach(
        AppServices(
            get_hitster_safe=get_fn,
            set_hitster_safe=set_fn,
            overrides=overrides,
            health_provider=health_provider,
        )
    )

    assert _client(out).get("/api/hitster-safe").get_json() == {"enabled": True}
    assert out._overrides is overrides
    assert out._health_fn is health_provider


# ---------------------------------------------------------------------------
# Apple TV pairing
# ---------------------------------------------------------------------------


def _fake_pairing_handler(device_provides_pin=True, has_paired=True, credentials="cafef00d"):
    handler = MagicMock()
    handler.device_provides_pin = device_provides_pin
    handler.begin = AsyncMock()
    handler.finish = AsyncMock()
    handler.close = AsyncMock()
    handler.has_paired = has_paired
    handler.service.credentials = credentials
    return handler


def _fake_scan_result(name="Living Room"):
    conf = MagicMock()
    conf.name = name
    return conf


@patch("pyatv.pair")
@patch("pyatv.scan")
def test_pair_start_with_device_provided_pin(mock_scan, mock_pair, config_path):
    mock_scan.return_value = [_fake_scan_result()]
    handler = _fake_pairing_handler(device_provides_pin=True)
    mock_pair.return_value = handler

    out = _output(config_path)
    client = _client(out)
    resp = client.post(
        "/api/appletv/pair/start",
        json={"host": "192.168.1.90", "protocol": "companion"},
    )

    data = resp.get_json()
    assert data["ok"] is True
    assert data["device_name"] == "Living Room"
    assert data["protocol"] == "companion"
    assert data["device_provides_pin"] is True
    assert data["manual_pin"] is None
    handler.pin.assert_not_called()


@patch("pyatv.pair")
@patch("pyatv.scan")
def test_pair_start_with_manual_pin(mock_scan, mock_pair, config_path):
    mock_scan.return_value = [_fake_scan_result()]
    handler = _fake_pairing_handler(device_provides_pin=False)
    mock_pair.return_value = handler

    out = _output(config_path)
    client = _client(out)
    resp = client.post("/api/appletv/pair/start", json={"host": "192.168.1.90", "protocol": "mrp"})

    data = resp.get_json()
    assert data["ok"] is True
    assert data["device_provides_pin"] is False
    assert data["manual_pin"] == 1234
    handler.pin.assert_called_once_with(1234)


@patch("pyatv.pair")
@patch("pyatv.scan")
def test_pair_start_requires_host(mock_scan, mock_pair, config_path):
    out = _output(config_path)
    client = _client(out)
    resp = client.post("/api/appletv/pair/start", json={"host": "", "protocol": "companion"})

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    mock_scan.assert_not_called()


@patch("pyatv.scan")
def test_pair_start_no_device_found(mock_scan, config_path):
    mock_scan.return_value = []

    out = _output(config_path)
    client = _client(out)
    resp = client.post("/api/appletv/pair/start", json={"host": "192.168.1.90"})

    data = resp.get_json()
    assert resp.status_code == 400
    assert data["ok"] is False
    assert "No Apple TV found" in data["error"]


@patch("pyatv.pair")
@patch("pyatv.scan")
def test_pair_start_rejects_unknown_protocol(mock_scan, mock_pair, config_path):
    mock_scan.return_value = [_fake_scan_result()]

    out = _output(config_path)
    client = _client(out)
    resp = client.post(
        "/api/appletv/pair/start", json={"host": "192.168.1.90", "protocol": "bogus"}
    )

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    mock_pair.assert_not_called()


@patch("pyatv.pair")
@patch("pyatv.scan")
def test_pair_start_rejects_concurrent_attempt(mock_scan, mock_pair, config_path):
    mock_scan.return_value = [_fake_scan_result()]
    mock_pair.return_value = _fake_pairing_handler()

    out = _output(config_path)
    client = _client(out)
    client.post("/api/appletv/pair/start", json={"host": "192.168.1.90"})
    resp = client.post("/api/appletv/pair/start", json={"host": "192.168.1.90"})

    assert resp.status_code == 400
    assert "already in progress" in resp.get_json()["error"]


@patch("pyatv.pair")
@patch("pyatv.scan")
def test_pair_finish_with_correct_pin_saves_credentials(mock_scan, mock_pair, config_path):
    mock_scan.return_value = [_fake_scan_result()]
    handler = _fake_pairing_handler(device_provides_pin=True, has_paired=True, credentials="abc123")
    mock_pair.return_value = handler

    out = _output(config_path)
    client = _client(out)
    client.post(
        "/api/appletv/pair/start",
        json={"host": "192.168.1.90", "protocol": "companion"},
    )
    resp = client.post("/api/appletv/pair/finish", json={"pin": "4321"})

    data = resp.get_json()
    assert data["ok"] is True
    assert data["protocol"] == "companion"
    assert data["field"] == "companion_credentials"
    assert data["credentials"] == "abc123"
    handler.pin.assert_called_once_with(4321)

    cfg = Config.load(config_path)
    assert cfg.sources["appletv"].companion_credentials == "abc123"
    assert cfg.sources["appletv"].enabled is True


@patch("pyatv.pair")
@patch("pyatv.scan")
def test_pair_finish_without_pin_when_required_fails(mock_scan, mock_pair, config_path):
    mock_scan.return_value = [_fake_scan_result()]
    handler = _fake_pairing_handler(device_provides_pin=True)
    mock_pair.return_value = handler

    out = _output(config_path)
    client = _client(out)
    client.post("/api/appletv/pair/start", json={"host": "192.168.1.90"})
    resp = client.post("/api/appletv/pair/finish", json={})

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


@patch("pyatv.pair")
@patch("pyatv.scan")
def test_pair_finish_with_manual_pin_does_not_require_pin_in_request(
    mock_scan, mock_pair, config_path
):
    mock_scan.return_value = [_fake_scan_result()]
    handler = _fake_pairing_handler(device_provides_pin=False, has_paired=True, credentials="xyz")
    mock_pair.return_value = handler

    out = _output(config_path)
    client = _client(out)
    client.post("/api/appletv/pair/start", json={"host": "192.168.1.90", "protocol": "mrp"})
    resp = client.post("/api/appletv/pair/finish", json={})

    data = resp.get_json()
    assert data["ok"] is True
    assert data["field"] == "mrp_credentials"

    cfg = Config.load(config_path)
    assert cfg.sources["appletv"].mrp_credentials == "xyz"


@patch("pyatv.pair")
@patch("pyatv.scan")
def test_pair_finish_when_pairing_fails(mock_scan, mock_pair, config_path):
    mock_scan.return_value = [_fake_scan_result()]
    handler = _fake_pairing_handler(device_provides_pin=True, has_paired=False)
    mock_pair.return_value = handler

    out = _output(config_path)
    client = _client(out)
    client.post("/api/appletv/pair/start", json={"host": "192.168.1.90"})
    resp = client.post("/api/appletv/pair/finish", json={"pin": "1111"})

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    handler.close.assert_awaited()


def test_pair_finish_without_start_fails(config_path):
    out = _output(config_path)
    client = _client(out)
    resp = client.post("/api/appletv/pair/finish", json={"pin": "1234"})

    assert resp.status_code == 400
    assert "No pairing in progress" in resp.get_json()["error"]


@patch("pyatv.pair")
@patch("pyatv.scan")
def test_pair_cancel_clears_session_and_allows_restart(mock_scan, mock_pair, config_path):
    mock_scan.return_value = [_fake_scan_result()]
    handler = _fake_pairing_handler()
    mock_pair.return_value = handler

    out = _output(config_path)
    client = _client(out)
    client.post("/api/appletv/pair/start", json={"host": "192.168.1.90"})
    cancel_resp = client.post("/api/appletv/pair/cancel")
    restart_resp = client.post("/api/appletv/pair/start", json={"host": "192.168.1.90"})

    assert cancel_resp.get_json() == {"ok": True}
    assert restart_resp.get_json()["ok"] is True
    handler.close.assert_awaited()


def test_pair_cancel_with_no_session_is_noop(config_path):
    out = _output(config_path)
    client = _client(out)
    resp = client.post("/api/appletv/pair/cancel")

    assert resp.get_json() == {"ok": True}


# ---------------------------------------------------------------------------
# Output ABC no-ops
# ---------------------------------------------------------------------------


def test_handles_images_is_false(config_path):
    out = _output(config_path)
    assert out.handles_images is False


def test_update_on_idle_on_new_item_are_noops(config_path):
    from unittest.mock import MagicMock

    out = _output(config_path)
    out.update(MagicMock(), MagicMock(), MagicMock())  # must not raise
    out.on_idle()
    out.on_new_item(MagicMock(), MagicMock())


# ---------------------------------------------------------------------------
# index page
# ---------------------------------------------------------------------------


def test_index_page_served(config_path):
    # "/" now serves the new Dashboard shell by default (Fas 2 of the GUI
    # redesign) - see tests/test_dashboard_shell.py for its dedicated
    # coverage. The classic shell (still titled "... configuration") lives
    # on at /form, tested separately below.
    out = _output(config_path)
    resp = _client(out).get("/")
    assert resp.status_code == 200
    assert b"mediainfo" in resp.data

    resp = _client(out).get("/form")
    assert resp.status_code == 200
    assert b"configuration" in resp.data


# ---------------------------------------------------------------------------
# library page and /api/library/*
# ---------------------------------------------------------------------------


def test_library_page_served(library_config_path):
    out = _output(library_config_path)
    resp = _client(out).get("/library")
    assert resp.status_code == 200
    assert b"library" in resp.data.lower()


def test_library_stats_empty(library_config_path):
    out = _output(library_config_path)
    resp = _client(out).get("/api/library/stats")
    assert resp.get_json() == {"artists": 0, "albums": 0, "tracks": 0}


def test_library_stats_counts_seeded_data(library_config_path):
    out = _output(library_config_path)
    library = out._get_library()
    artist_id = library.get_or_create_artist("Pink Floyd")
    library.get_or_create_album(artist_id, "The Wall")
    library.get_or_create_track(artist_id, "Money")

    resp = _client(out).get("/api/library/stats")
    assert resp.get_json() == {"artists": 1, "albums": 1, "tracks": 1}


def test_library_search_empty_query_returns_empty_list(library_config_path):
    out = _output(library_config_path)
    resp = _client(out).get("/api/library/search")
    assert resp.get_json() == []


def test_library_search_returns_matching_artists(library_config_path):
    out = _output(library_config_path)
    library = out._get_library()
    library.get_or_create_artist("Pink Floyd")
    library.get_or_create_artist("Queen")

    resp = _client(out).get("/api/library/search?q=pink")
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["name"] == "Pink Floyd"
    assert isinstance(data[0]["id"], int)


def test_library_search_is_fuzzy(library_config_path):
    out = _output(library_config_path)
    library = out._get_library()
    library.get_or_create_artist("Simon & Garfunkel")

    resp = _client(out).get("/api/library/search?q=simon and garfunkel")
    assert [a["name"] for a in resp.get_json()] == ["Simon & Garfunkel"]


def test_library_artist_returns_albums_and_tracks(library_config_path):
    out = _output(library_config_path)
    library = out._get_library()
    artist_id = library.get_or_create_artist("Pink Floyd")
    library.set_mbid("artist", artist_id, "artist-mbid")
    album_id = library.get_or_create_album(artist_id, "The Wall")
    library.set_mbid("album", album_id, "album-mbid")
    library.get_or_create_track(artist_id, "Money")

    resp = _client(out).get(f"/api/library/artist/{artist_id}")
    data = resp.get_json()
    assert data["name"] == "Pink Floyd"
    assert data["mbid"] == "artist-mbid"
    assert data["albums"] == [{"id": album_id, "title": "The Wall", "mbid": "album-mbid"}]
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["title"] == "Money"


def test_library_artist_not_found_returns_404(library_config_path):
    out = _output(library_config_path)
    resp = _client(out).get("/api/library/artist/999")
    assert resp.status_code == 404


def test_get_library_reuses_connection_across_requests(library_config_path):
    out = _output(library_config_path)
    lib1 = out._get_library()
    lib2 = out._get_library()
    assert lib1 is lib2


# Optional auth: no longer tested per-output - install_auth() is called
# once, centrally, by SharedHttpServer (mediainfo/outputs/http_server.py),
# not by ConfigUiOutput itself. See tests/test_web_auth.py (the private/
# public address + Basic Auth logic itself) and tests/test_http_server.py
# (the CSRF-header guard, wired the same way).
#
# _is_exposed_without_auth() itself is still this output's own logic (it
# only drives a warning banner, not enforcement) - now checking the shared
# server's http_host instead of a per-output config.host (H1).


def test_exposed_without_auth_true_for_lan_host_with_no_auth(config_path):
    out = ConfigUiOutput(_config(), config_path, http_host="0.0.0.0")
    assert out._is_exposed_without_auth() is True


def test_exposed_without_auth_false_for_loopback_host(config_path):
    out = ConfigUiOutput(_config(), config_path, http_host="127.0.0.1")
    assert out._is_exposed_without_auth() is False


def test_exposed_without_auth_false_when_auth_enabled(config_path):
    from mediainfo.config import AuthConfig

    auth = AuthConfig(enabled=True, username="admin", password="secret")
    out = ConfigUiOutput(_config(), config_path, auth, http_host="0.0.0.0")
    assert out._is_exposed_without_auth() is False


def test_overview_reports_exposed_without_auth(config_path):
    out = ConfigUiOutput(_config(), config_path, http_host="0.0.0.0")
    data = _client(out).get("/api/overview").get_json()
    assert data["exposed_without_auth"] is True


# ---------------------------------------------------------------------------
# Single-page shell (templates/config_ui/app.html), served identically at
# "/form" and "/dashboard" - only the initially-selected nav section
# (encoded as `data-initial-section` on <body>, read by client JS) differs
# by route/`ui`. This replaced the old two-separate-templates design (a
# full editable form vs. a read-only dashboard) with one guided app shell;
# these tests check the new contract instead of the old templates' markup.
# Since Fas 2 of the GUI redesign, "/" itself serves a *different*, newer
# shell for the default `ui: form` config - see
# tests/test_dashboard_shell.py - except when `ui: dashboard` is set, where
# "/" keeps landing on this classic shell unchanged (next test).
# ---------------------------------------------------------------------------


def test_dashboard_ui_serves_dashboard_page(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = _client(out).get("/")
    assert resp.status_code == 200
    assert b'data-initial-section="status"' in resp.data


def test_form_page_reachable_on_dashboard_instance(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = _client(out).get("/form")
    assert resp.status_code == 200
    assert b'data-initial-section="overview"' in resp.data


def test_dashboard_page_reachable_on_form_instance(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = _client(out).get("/dashboard")
    assert resp.status_code == 200
    assert b'data-initial-section="status"' in resp.data


def test_all_nav_sections_present_on_every_route(config_path):
    # "/" is intentionally excluded here - since Fas 2 it serves the new
    # Dashboard shell, not this classic one - see
    # tests/test_dashboard_shell.py for its nav coverage.
    out = ConfigUiOutput(_config(), config_path)
    client = _client(out)
    expected_sections = [
        "overview",
        "sources",
        "outputs",
        "artwork",
        "idle",
        "automation",
        "library",
        "status",
        "advanced",
    ]
    for route in ("/form", "/dashboard"):
        data = client.get(route).data
        for section in expected_sections:
            assert f'data-section="{section}"'.encode() in data, (
                f"{section} missing from nav on {route}"
            )


def test_editing_capability_lives_in_guided_sections_not_status(config_path):
    # Editing moved from an old "read-only dashboard with inline edit
    # cards" design to the dedicated Media sources/Displays & outputs/
    # Artwork & metadata sections - the shell still ships one JS function
    # that writes field edits (setValue/setOutputField), used by all of
    # them, rather than a status-page-only edit mode.
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = _client(out).get("/dashboard")
    assert b"function setValue(" in resp.data
    assert b"function setOutputField(" in resp.data
    assert b"function renderStatus()" in resp.data


def test_dashboard_instance_can_read_schema_and_config_for_editing(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    client = _client(out)

    schema = client.get("/api/schema").get_json()
    assert "kodi" in schema["sources"]

    config = client.get("/api/config").get_json()
    assert config["values"]["sources.kodi.host"] == "192.168.1.21"


def test_dashboard_instance_can_save_form_edits(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    client = _client(out)

    resp = client.post(
        "/api/config/form",
        json={"values": {"sources.kodi.host": "192.168.50.50"}},
    )
    assert resp.get_json() == {"ok": True, "restart_required": False}


def test_dashboard_page_has_restart_button(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = _client(out).get("/dashboard")
    assert b"function restartNow(" in resp.data
    assert b"/api/restart" in resp.data
    assert b"Restart now" in resp.data or b"Restart mediainfo" in resp.data


def test_dashboard_page_marks_failed_source_test_as_unavailable(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = _client(out).get("/dashboard")
    assert b"statusOverrides[key" in resp.data
    assert b"'unavailable'" in resp.data
    assert b"b-unavailable" in resp.data
    assert b"'unavailable'" in resp.data and b"data-filter=" in resp.data


def test_api_status_returns_empty_lists_without_health_provider(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = _client(out).get("/api/status")
    assert resp.get_json() == {
        "sources": [],
        "outputs": [],
        "enrichers": [],
        "idle_sources": [],
    }


def test_api_status_returns_health_provider_data(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    out.set_health_provider(
        lambda: {
            "sources": [{"name": "kodi", "status": "active"}],
            "outputs": [{"type": "web", "status": "ok", "port": 8090}],
            "enrichers": [{"name": "musicbrainz", "status": "ok"}],
            "now_playing": None,
        }
    )

    resp = _client(out).get("/api/status")
    data = resp.get_json()

    assert data["sources"] == [{"name": "kodi", "status": "active"}]
    assert data["outputs"] == [{"type": "web", "status": "ok", "port": 8090}]
    assert data["enrichers"] == [{"name": "musicbrainz", "status": "ok"}]
    assert "now_playing" not in data  # only sources/outputs/enrichers are exposed


def test_api_test_source_route_dispatches(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    with patch("mediainfo.outputs.config_ui.test_source", return_value=(True, "ok")) as mock_test:
        resp = _client(out).post("/api/test/source/kodi")

    assert resp.get_json() == {"ok": True, "message": "ok"}
    name_arg, config_arg = mock_test.call_args.args
    assert name_arg == "kodi"


def test_api_test_enricher_route_dispatches(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    with patch(
        "mediainfo.outputs.config_ui.test_enricher", return_value=(False, "no")
    ) as mock_test:
        resp = _client(out).post("/api/test/enricher/thetvdb")

    assert resp.get_json() == {"ok": False, "message": "no"}
    name_arg, _ = mock_test.call_args.args
    assert name_arg == "thetvdb"


def test_api_test_output_route_dispatches(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    with patch(
        "mediainfo.outputs.config_ui.test_output", return_value=(True, "reached")
    ) as mock_test:
        resp = _client(out).post(
            "/api/test/output",
            json={"type": "pixoo", "ip": "192.168.1.32"},
        )

    assert resp.get_json() == {"ok": True, "message": "reached"}
    mock_test.assert_called_once_with("pixoo", {"type": "pixoo", "ip": "192.168.1.32"})


def test_api_test_output_route_handles_missing_body(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    with patch(
        "mediainfo.outputs.config_ui.test_output",
        return_value=(False, "No connection test"),
    ):
        resp = _client(out).post("/api/test/output")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# Artwork overrides
# ---------------------------------------------------------------------------


def test_overrides_page_served(config_path):
    out = _output(config_path)
    resp = _client(out).get("/overrides")
    assert resp.status_code == 200
    assert b"overrides" in resp.data.lower()


def test_overrides_list_reports_disabled_when_no_store_registered(config_path):
    out = _output(config_path)
    resp = _client(out).get("/api/overrides")
    assert resp.get_json() == {"enabled": False, "items": []}


def test_overrides_list_empty_when_enabled(config_path, tmp_path):
    from mediainfo.artwork_overrides import ArtworkOverrideStore

    out = _output(config_path)
    out.set_artwork_overrides(ArtworkOverrideStore(str(tmp_path / "overrides")))

    resp = _client(out).get("/api/overrides")

    assert resp.get_json() == {"enabled": True, "items": []}


def test_overrides_add_then_list(config_path, tmp_path):
    import io

    from mediainfo.artwork_overrides import ArtworkOverrideStore

    out = _output(config_path)
    out.set_artwork_overrides(ArtworkOverrideStore(str(tmp_path / "overrides")))

    resp = _client(out).post(
        "/api/overrides",
        data={
            "title": "Inception",
            "subtitle": "",
            "file": (io.BytesIO(b"fake-image-bytes"), "poster.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert resp.get_json() == {"ok": True}

    listed = _client(out).get("/api/overrides").get_json()
    assert listed["enabled"] is True
    assert len(listed["items"]) == 1
    assert listed["items"][0]["title"] == "Inception"


def test_overrides_add_without_title_is_rejected(config_path, tmp_path):
    import io

    from mediainfo.artwork_overrides import ArtworkOverrideStore

    out = _output(config_path)
    out.set_artwork_overrides(ArtworkOverrideStore(str(tmp_path / "overrides")))

    resp = _client(out).post(
        "/api/overrides",
        data={"title": "", "file": (io.BytesIO(b"x"), "poster.jpg")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_overrides_add_without_file_is_rejected(config_path, tmp_path):
    from mediainfo.artwork_overrides import ArtworkOverrideStore

    out = _output(config_path)
    out.set_artwork_overrides(ArtworkOverrideStore(str(tmp_path / "overrides")))

    resp = _client(out).post(
        "/api/overrides",
        data={"title": "Inception"},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_overrides_add_when_disabled_returns_503(config_path):
    import io

    out = _output(config_path)
    resp = _client(out).post(
        "/api/overrides",
        data={"title": "Inception", "file": (io.BytesIO(b"x"), "poster.jpg")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 503


def test_overrides_remove(config_path, tmp_path):
    import io

    from mediainfo.artwork_overrides import ArtworkOverrideStore

    out = _output(config_path)
    out.set_artwork_overrides(ArtworkOverrideStore(str(tmp_path / "overrides")))
    _client(out).post(
        "/api/overrides",
        data={"title": "Inception", "file": (io.BytesIO(b"x"), "poster.jpg")},
        content_type="multipart/form-data",
    )

    resp = _client(out).delete(
        "/api/overrides",
        json={"title": "Inception", "subtitle": ""},
    )

    assert resp.get_json() == {"ok": True}
    assert _client(out).get("/api/overrides").get_json()["items"] == []


def test_overrides_remove_when_disabled_returns_503(config_path):
    out = _output(config_path)
    resp = _client(out).delete("/api/overrides", json={"title": "Inception"})
    assert resp.status_code == 503


def test_overrides_image_served(config_path, tmp_path):
    import io

    from mediainfo.artwork_overrides import ArtworkOverrideStore

    out = _output(config_path)
    out.set_artwork_overrides(ArtworkOverrideStore(str(tmp_path / "overrides")))
    _client(out).post(
        "/api/overrides",
        data={
            "title": "Inception",
            "file": (io.BytesIO(b"fake-image-bytes"), "poster.jpg"),
        },
        content_type="multipart/form-data",
    )
    filename = _client(out).get("/api/overrides").get_json()["items"][0]["filename"]

    resp = _client(out).get(f"/api/overrides/image/{filename}")

    assert resp.status_code == 200
    assert resp.data == b"fake-image-bytes"


def test_overrides_image_rejects_path_traversal(config_path, tmp_path):
    from mediainfo.artwork_overrides import ArtworkOverrideStore

    out = _output(config_path)
    out.set_artwork_overrides(ArtworkOverrideStore(str(tmp_path / "overrides")))

    resp = _client(out).get("/api/overrides/image/..%2F..%2Fetc%2Fpasswd")

    assert resp.status_code == 404


def test_overrides_image_404_when_disabled(config_path):
    out = _output(config_path)
    resp = _client(out).get("/api/overrides/image/whatever.jpg")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Filter meta and per-output filter fields
# ---------------------------------------------------------------------------


def test_schema_filter_meta_has_media_types_and_known_sources(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    fm = data["filter_meta"]
    assert set(fm["media_types"]) == {"music", "movie", "episode"}
    assert "kodi" in fm["known_sources"]
    assert "plex" in fm["known_sources"]


def test_schema_filter_fields_excluded_from_outputs_fields(config_path):
    out = _output(config_path)
    data = _client(out).get("/api/schema").get_json()
    for type_name, fields in data["outputs"].items():
        field_names = {f["name"] for f in fields}
        for filter_field in (
            "allow_media_types",
            "deny_media_types",
            "allow_sources",
            "deny_sources",
            "idle_when_filtered",
            "active_hours",
        ):
            assert filter_field not in field_names, (
                f"{filter_field} should not appear in schema.outputs.{type_name}"
            )


def test_get_config_outputs_includes_filter_fields(config_path):
    config_path.write_text(
        "outputs:\n  web:\n    - enabled: true\n      port: 8090\n      allow_media_types: [music]\n"
    )
    out = _output(config_path)
    data = _client(out).get("/api/config").get_json()
    assert data["outputs"]["web"][0]["allow_media_types"] == ["music"]
    assert data["outputs"]["web"][0]["deny_media_types"] == []


def test_save_form_saves_allow_media_types(config_path):
    config_path.write_text("outputs:\n  web:\n    - enabled: true\n      port: 8090\n")
    out = _output(config_path)
    client = _client(out)
    resp = client.post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "web": [
                    {
                        "enabled": True,
                        "port": 8090,
                        "allow_media_types": ["music", "movie"],
                        "deny_media_types": [],
                        "allow_sources": [],
                        "deny_sources": [],
                        "idle_when_filtered": False,
                        "active_hours": "",
                    }
                ]
            },
        },
    )
    assert resp.get_json() == {"ok": True, "restart_required": True}
    cfg = Config.load(config_path)
    assert cfg.outputs["web"][0].allow_media_types == ["music", "movie"]


def test_save_form_cleans_empty_filter_lists_from_yaml(config_path):
    config_path.write_text("outputs:\n  web:\n    - enabled: true\n      port: 8090\n")
    out = _output(config_path)
    client = _client(out)
    client.post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "web": [
                    {
                        "enabled": True,
                        "port": 8090,
                        "allow_media_types": [],
                        "deny_media_types": [],
                        "allow_sources": [],
                        "deny_sources": [],
                        "idle_when_filtered": False,
                        "active_hours": "",
                    }
                ]
            },
        },
    )
    text = config_path.read_text()
    for field in (
        "allow_media_types",
        "deny_media_types",
        "allow_sources",
        "deny_sources",
        "idle_when_filtered",
        "active_hours",
    ):
        assert field not in text


def test_save_form_rejects_conflicting_allow_deny_media_types(config_path):
    config_path.write_text("outputs:\n  web:\n    - enabled: true\n      port: 8090\n")
    out = _output(config_path)
    resp = _client(out).post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "web": [
                    {
                        "enabled": True,
                        "port": 8090,
                        "allow_media_types": ["music"],
                        "deny_media_types": ["music"],
                        "allow_sources": [],
                        "deny_sources": [],
                        "idle_when_filtered": False,
                        "active_hours": "",
                    }
                ]
            },
        },
    )
    data = resp.get_json()
    assert data["ok"] is False
    assert "music" in data["error"]


def test_save_form_rejects_conflicting_allow_deny_sources(config_path):
    config_path.write_text("outputs:\n  web:\n    - enabled: true\n      port: 8090\n")
    out = _output(config_path)
    resp = _client(out).post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "web": [
                    {
                        "enabled": True,
                        "port": 8090,
                        "allow_media_types": [],
                        "deny_media_types": [],
                        "allow_sources": ["kodi"],
                        "deny_sources": ["kodi"],
                        "idle_when_filtered": False,
                        "active_hours": "",
                    }
                ]
            },
        },
    )
    data = resp.get_json()
    assert data["ok"] is False
    assert "kodi" in data["error"]


def test_save_form_rejects_invalid_active_hours(config_path):
    config_path.write_text("outputs:\n  web:\n    - enabled: true\n      port: 8090\n")
    out = _output(config_path)
    resp = _client(out).post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "web": [
                    {
                        "enabled": True,
                        "port": 8090,
                        "allow_media_types": [],
                        "deny_media_types": [],
                        "allow_sources": [],
                        "deny_sources": [],
                        "idle_when_filtered": False,
                        "active_hours": "not-a-time",
                    }
                ]
            },
        },
    )
    data = resp.get_json()
    assert data["ok"] is False
    assert "active_hours" in data["error"]


def test_save_form_accepts_valid_active_hours_with_midnight_wrap(config_path):
    config_path.write_text("outputs:\n  web:\n    - enabled: true\n      port: 8090\n")
    out = _output(config_path)
    resp = _client(out).post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "web": [
                    {
                        "enabled": True,
                        "port": 8090,
                        "allow_media_types": [],
                        "deny_media_types": [],
                        "allow_sources": [],
                        "deny_sources": [],
                        "idle_when_filtered": False,
                        "active_hours": "22:00-06:00",
                    }
                ]
            },
        },
    )
    assert resp.get_json() == {"ok": True, "restart_required": True}
    cfg = Config.load(config_path)
    assert cfg.outputs["web"][0].active_hours == "22:00-06:00"
