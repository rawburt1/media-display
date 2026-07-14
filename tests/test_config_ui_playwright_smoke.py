"""Playwright smoke suite (N5 - see
docs/architecture-usability-review-2026-07.md): a small, CI-integrated
real-browser check of the config UI, "the least-tested code in the repo
while being the most user-facing" per that review (105 KB of hand-written
SPA JS with no client-side test coverage at all before this file).

Boots a real SharedHttpServer (the same class __main__.py uses - see
mediainfo/outputs/http_server.py) against an isolated scratch config on a
random free port, drives it with a real headless Chromium via Playwright,
and tears it down. Deliberately not a Flask test_client check - that
can't catch client-side JS bugs at all, which is exactly the gap this
file closes. This project already found real bugs this way that HTML/
attribute grepping missed (see the project_config_ui_ux_punchlist memory
this session inherited) - a Flask test_client response body looking
correct says nothing about whether the browser that renders it hits a
console error, loses focus, or leaks a secret into the DOM.

Scope deliberately narrow, matching the review's own suggested checks:
loads, nav works, a save round-trips a field, a secret never reaches the
DOM. Not a general Playwright framework for this codebase.

Skips itself (not fails) if playwright isn't installed/its browsers
aren't downloaded - matches this project's "missing dependencies must not
crash the app" convention (see requirements-dev.txt for why it's listed
there, and .github/workflows/tests.yml for the CI job that installs it).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
import yaml

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from mediainfo import wiring  # noqa: E402
from mediainfo.cache import ImageCache  # noqa: E402
from mediainfo.config import Config  # noqa: E402
from mediainfo.outputs.http_server import SharedHttpServer  # noqa: E402

# A real (fake-value) secret in both a source and an enricher, checked
# never to leak into any page's rendered HTML - not just a schema/API
# response, which tests/test_config_ui.py already covers extensively.
_KODI_PASSWORD = "sm0ke-test-s3cret-password"
_FANARTTV_API_KEY = "sm0ke-test-s3cret-api-key"

_SCRATCH_CONFIG_YAML = f"""
priority:
  - kodi
sources:
  kodi:
    enabled: true
    host: 192.168.1.99
    username: testuser
    password: {_KODI_PASSWORD}
outputs:
  web:
    enabled: true
  config:
    enabled: true
    ui: form
enrichers:
  fanarttv:
    enabled: true
    api_key: {_FANARTTV_API_KEY}
"""


@pytest.fixture
def scratch_config_path(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    data = yaml.safe_load(_SCRATCH_CONFIG_YAML)
    # Isolated cache/library/etc - never touch real data (see this
    # session's own project_local_run_isolation memory).
    data["cache"] = {"dir": str(tmp_path / "cache")}
    data["library"] = {"db_path": str(tmp_path / "library.db")}
    data["overrides"] = {"dir": str(tmp_path / "overrides")}
    data["posters"] = {"dir": str(tmp_path / "posters")}
    data["history"] = {"db_path": str(tmp_path / "history.db")}
    data["mediadata"] = {"dir": str(tmp_path / "mediadata")}
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return config_path


@pytest.fixture
def live_app_url(scratch_config_path: Path) -> Iterator[str]:
    """Boot the real HTTP layer (web + config outputs) on a random free
    port - not the orchestrator (no sources are actually polled), which
    this suite's scope doesn't need and which would otherwise require
    mocking every background-thread-spawning source (AppleTv/YouTube/
    Shield's ADB loop, HomeAssistant's websocket, MQTT, ...) - kodi alone
    doesn't spawn one, so nothing here does either.
    """
    config = Config.load(scratch_config_path)
    config.http.host = "127.0.0.1"
    config.http.port = 0
    cache = ImageCache(config.cache.dir)
    server = SharedHttpServer(config.http, config.auth)
    outputs = wiring.instantiate_outputs(config, scratch_config_path, cache, server)
    server.start()
    assert server._server is not None
    try:
        yield f"http://127.0.0.1:{server._server.server_port}"
    finally:
        server.stop()
        for output in outputs:
            stop = getattr(output, "stop", None)
            if callable(stop):
                stop()


@pytest.fixture
def page(live_app_url):
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # pragma: no cover - depends on local install
            pytest.skip(f"Chromium isn't installed for playwright: {exc}")
        pg = browser.new_page()
        console_errors = []
        pg.on(
            "console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None
        )
        pg.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
        pg.console_errors = console_errors  # type: ignore[attr-defined]
        pg.base_url = live_app_url  # type: ignore[attr-defined]
        yield pg
        browser.close()


def test_now_playing_display_loads(page):
    page.goto(page.base_url + "/", wait_until="networkidle")
    assert page.title() != ""
    assert page.console_errors == []


def test_config_ui_loads_with_no_console_errors(page):
    page.goto(page.base_url + "/config/", wait_until="networkidle")
    page.wait_for_timeout(400)
    assert page.query_selector("#nav") is not None
    assert page.console_errors == []


def test_nav_sections_all_render_without_console_errors(page):
    page.goto(page.base_url + "/config/", wait_until="networkidle")
    page.wait_for_timeout(400)
    for section in (
        "dashboard",
        "pipeline",
        "media",
        "metadata",
        "appearance",
        "displays",
        "library",
        "health",
        "advanced",
    ):
        page.click(f'#nav button[data-section="{section}"]')
        page.wait_for_timeout(300)
    assert page.console_errors == []


def test_save_round_trips_a_field(page, scratch_config_path):
    page.goto(page.base_url + "/config/", wait_until="networkidle")
    page.wait_for_timeout(400)
    page.click('#nav button[data-section="media"]')
    page.wait_for_timeout(300)
    page.click('a.component-card[href="#component/sources.kodi"]')
    page.wait_for_timeout(400)

    host_input = page.query_selector("#section-component input[type=text]")
    host_input.click()
    host_input.fill("")
    host_input.type("192.168.1.222")
    host_input.evaluate("el => el.blur()")
    page.wait_for_timeout(300)

    page.click("#section-component button:has-text('Save')", force=True)
    page.wait_for_timeout(800)

    saved = yaml.safe_load(scratch_config_path.read_text(encoding="utf-8"))
    assert saved["sources"]["kodi"]["host"] == "192.168.1.222"
    assert page.console_errors == []


def test_secrets_never_reach_the_dom(page):
    page.goto(page.base_url + "/config/", wait_until="networkidle")
    page.wait_for_timeout(400)

    page.click('#nav button[data-section="media"]')
    page.wait_for_timeout(300)
    page.click('a.component-card[href="#component/sources.kodi"]')
    page.wait_for_timeout(400)
    assert _KODI_PASSWORD not in page.content()

    page.click("a.back-link")
    page.wait_for_timeout(200)
    page.click('#nav button[data-section="metadata"]')
    page.wait_for_timeout(300)
    page.click('a.component-card[href="#component/enrichers.fanarttv"]')
    page.wait_for_timeout(400)
    assert _FANARTTV_API_KEY not in page.content()
