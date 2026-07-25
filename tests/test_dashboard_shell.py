"""Tests for the Dashboard shell: the single "/" landing page
(templates/config_ui/dashboard.html + static/config_ui/dashboard.*). The
classic shell it once linked out to (templates/config_ui/app.html) is gone
- see docs/adr/0001-config-ui-two-shell-migration-and-request-lifecycle.md
(H5 finished the migration that ADR describes as mid-flight) - so the `ui`
config flag no longer changes which shell "/" serves; it's kept only so
existing config.yaml files that set it still load. See
docs/gui-redesign-phase0-inventory.md for the overall plan.
"""

import shutil
from pathlib import Path

import pytest
from flask import Flask

from mediainfo.config import ConfigUiConfig
from mediainfo.configui.output import ConfigUiOutput

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


def _config(**kwargs):
    return ConfigUiConfig(enabled=True, **kwargs)


def _client(out, url_prefix=""):
    """See tests/test_nest_hub.py for the harness pattern (H1, see
    docs/architecture-usability-review-2026-07.md). Built as
    Flask("mediainfo.outputs.config_ui") so templates/ and the blueprint's
    own static_folder resolve - see tests/test_feeds.py for why."""
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


# ---------------------------------------------------------------------------
# "/" always serves the one shell now, regardless of `ui`
# ---------------------------------------------------------------------------


def test_root_serves_dashboard_shell_by_default(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = _client(out).get("/")
    assert resp.status_code == 200
    body = resp.data
    assert b'data-section="dashboard"' in body
    assert b'data-section="advanced"' in body


def test_root_with_ui_dashboard_serves_the_same_shell(config_path):
    # `ui: dashboard` no longer branches to anything - see this file's
    # module docstring - it's just a legacy value that must not error.
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = _client(out).get("/")
    assert resp.status_code == 200
    assert b'data-section="dashboard"' in resp.data


def test_form_and_dashboard_routes_still_work(config_path):
    out = ConfigUiOutput(_config(), config_path)
    client = _client(out)
    # /form predates the single-shell nav - kept as a redirect so an old
    # bookmark still lands somewhere useful.
    form_resp = client.get("/form", follow_redirects=False)
    assert form_resp.status_code == 302
    assert form_resp.headers["Location"].endswith("/#advanced")
    # /dashboard is a plain alias for "/" (same shell, same markup).
    assert b'data-section="dashboard"' in client.get("/dashboard").data


# ---------------------------------------------------------------------------
# Nav: every section is rendered in-shell, none link out anymore
# ---------------------------------------------------------------------------


def test_new_shell_nav_has_in_shell_sections(config_path):
    # Media/Metadata/Appearance/Displays (Fas 4), Health (Fas 6), Library
    # (Fas 7), and finally Advanced (H5) are all rendered in-shell via
    # client-side hash routing (see static/config_ui/components.js and
    # advanced.js) - nothing in the primary nav links to a separate page.
    out = ConfigUiOutput(_config(), config_path)
    body = _client(out).get("/").data
    for section in (
        b"media",
        b"metadata",
        b"appearance",
        b"displays",
        b"library",
        b"health",
        b"advanced",
    ):
        assert b'data-section="' + section + b'"' in body, section


def test_pipeline_and_history_are_not_top_level_nav_buttons(config_path):
    # Foreman 005 (see docs/foreman/005.md): Pipeline nests under Dashboard
    # and History nests under Library, one hash segment deeper
    # (#dashboard/pipeline, #library/history) - neither gets its own
    # #nav button anymore.
    out = ConfigUiOutput(_config(), config_path)
    body = _client(out).get("/").data
    assert b'data-section="pipeline"' not in body
    assert b'data-section="history"' not in body
    assert b'id="section-pipeline"' not in body
    assert b'id="section-history"' not in body


def test_help_moved_to_sidebar_footer_not_primary_nav(config_path):
    # Foreman 005: Help is a fully static reference page, the cheapest of
    # the eleven original top-level items to demote - it moved into the
    # sidebar footer next to Theme/Hitster-safe instead of #nav.
    out = ConfigUiOutput(_config(), config_path)
    body = _client(out).get("/").data
    assert b'data-section="help"' not in body
    assert b'id="help-nav-btn"' in body
    assert b'id="section-help"' in body  # the section itself is unchanged


def test_new_shell_nav_has_no_links_to_the_old_classic_shell(config_path):
    out = ConfigUiOutput(_config(), config_path)
    body = _client(out).get("/").data
    assert b"/form" not in body


# ---------------------------------------------------------------------------
# Auth warning banner reaches the new shell too, same as the classic one
# ---------------------------------------------------------------------------


def test_new_shell_shows_auth_warning_for_non_loopback_caller(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = _client(out).get("/", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
    assert b"No authentication" in resp.data


def test_new_shell_no_auth_warning_for_loopback_caller(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = _client(out).get("/")
    assert b"No authentication" not in resp.data


# ---------------------------------------------------------------------------
# Static assets
# ---------------------------------------------------------------------------


def test_dashboard_static_js_is_served(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = _client(out).get("/static/dashboard.js")
    assert resp.status_code == 200


def test_components_static_js_is_served(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = _client(out).get("/static/components.js")
    assert resp.status_code == 200


def test_advanced_static_js_is_served(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = _client(out).get("/static/advanced.js")
    assert resp.status_code == 200


def test_dashboard_static_css_is_served(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = _client(out).get("/static/dashboard.css")
    assert resp.status_code == 200
