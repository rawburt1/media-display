"""Tests for the Fas 2 GUI-redesign Dashboard shell: the new "/" landing
page (templates/config_ui/dashboard.html + static/config_ui/dashboard.*)
and how it interacts with the classic shell/`ui` config flag. See
docs/gui-redesign-phase0-inventory.md for the overall plan.
"""

import shutil
from pathlib import Path

import pytest

from mediainfo.config import ConfigUiConfig
from mediainfo.outputs.config_ui import ConfigUiOutput

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


@pytest.fixture(autouse=True)
def no_server(monkeypatch):
    monkeypatch.setattr("threading.Thread.start", lambda self: None)


def _config(**kwargs):
    return ConfigUiConfig(enabled=True, host="127.0.0.1", port=8094, **kwargs)


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    shutil.copy(EXAMPLE_CONFIG, path)
    return path


# ---------------------------------------------------------------------------
# "/" serves the new shell by default; `ui: dashboard` keeps the classic one
# ---------------------------------------------------------------------------


def test_root_serves_new_dashboard_shell_by_default(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = out.app.test_client().get("/")
    assert resp.status_code == 200
    body = resp.data
    assert b'data-section="dashboard"' in body
    assert b'data-section="pipeline"' in body
    # Not the classic shell's markers.
    assert b"data-initial-section" not in body


def test_root_with_ui_dashboard_still_serves_classic_status_shell(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = out.app.test_client().get("/")
    assert resp.status_code == 200
    assert b'data-initial-section="status"' in resp.data


def test_form_and_dashboard_routes_are_unaffected(config_path):
    out = ConfigUiOutput(_config(), config_path)
    client = out.app.test_client()
    assert b'data-initial-section="overview"' in client.get("/form").data
    assert b'data-initial-section="status"' in client.get("/dashboard").data


# ---------------------------------------------------------------------------
# New nav: two JS-rendered sections + real links into the classic shell
# ---------------------------------------------------------------------------


def test_new_shell_nav_has_in_shell_category_sections(config_path):
    # Since Fas 4, Media/Metadata/Appearance/Displays are rendered in-shell
    # (client-side hash routing, see static/config_ui/components.js)
    # rather than linking out to the classic shell; Health joined them in
    # Fas 6 and Library in Fas 7 - only Advanced remains a plain link
    # (next test).
    out = ConfigUiOutput(_config(), config_path)
    body = out.app.test_client().get("/").data
    for section in (b"media", b"metadata", b"appearance", b"displays", b"library", b"health"):
        assert b'data-section="' + section + b'"' in body, section


def test_new_shell_nav_links_into_classic_sections(config_path):
    out = ConfigUiOutput(_config(), config_path)
    body = out.app.test_client().get("/").data
    assert b'href="/form"' in body


# ---------------------------------------------------------------------------
# Auth warning banner reaches the new shell too, same as the classic one
# ---------------------------------------------------------------------------


def test_new_shell_shows_auth_warning_for_non_loopback_caller(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = out.app.test_client().get("/", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
    assert b"No authentication" in resp.data


def test_new_shell_no_auth_warning_for_loopback_caller(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = out.app.test_client().get("/")
    assert b"No authentication" not in resp.data


# ---------------------------------------------------------------------------
# Static assets
# ---------------------------------------------------------------------------


def test_dashboard_static_js_is_served(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = out.app.test_client().get("/static/config_ui/dashboard.js")
    assert resp.status_code == 200


def test_components_static_js_is_served(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = out.app.test_client().get("/static/config_ui/components.js")
    assert resp.status_code == 200


def test_dashboard_static_css_is_served(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = out.app.test_client().get("/static/config_ui/dashboard.css")
    assert resp.status_code == 200
