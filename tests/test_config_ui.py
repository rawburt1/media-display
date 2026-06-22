"""Tests for the config output (web UI for editing config.yaml)."""

import asyncio
import os
import shutil
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mediainfo.config import Config, ConfigUiConfig
from mediainfo.outputs.config_ui import ConfigUiOutput, _restart_process

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


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
    monkeypatch.setattr(ConfigUiOutput, "_stop_appletv_loop", staticmethod(lambda loop, thread: None))


def _config(**kwargs):
    return ConfigUiConfig(enabled=True, host="127.0.0.1", port=8094, **kwargs)


def _output(config_path):
    return ConfigUiOutput(_config(), config_path)


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


# ---------------------------------------------------------------------------
# /api/schema
# ---------------------------------------------------------------------------

def test_schema_includes_all_categories(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/schema").get_json()
    assert set(data.keys()) == {"general", "cache", "sources", "outputs", "enrichers", "idle"}


def test_schema_includes_known_source_types(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/schema").get_json()
    assert "kodi" in data["sources"]
    assert "plex" in data["sources"]


def test_schema_includes_simple_list_fields(config_path):
    # speaker_ips/blacklist are flat lists of strings - simple enough to
    # edit as a one-item-per-line text box in the form.
    out = _output(config_path)
    data = out.app.test_client().get("/api/schema").get_json()
    fields = {f["name"]: f for f in data["sources"]["sonos"]}
    assert fields["blacklist"]["type"] == "list"
    assert fields["blacklist"]["default"] == []
    assert fields["speaker_ips"]["type"] == "list"
    assert "enabled" in fields


def test_schema_excludes_complex_list_typed_fields(config_path):
    # `transforms` is a list of differently-shaped objects, not a flat
    # list of strings - excluded from the form, only editable via the
    # page's "Advanced" raw YAML editor.
    out = _output(config_path)
    data = out.app.test_client().get("/api/schema").get_json()
    field_names = {f["name"] for f in data["outputs"]["pixoo"]}
    assert "transforms" not in field_names
    assert "ip" in field_names


def test_schema_marks_secret_fields(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/schema").get_json()
    fields = {f["name"]: f for f in data["enrichers"]["fanarttv"]}
    assert fields["api_key"]["secret"] is True


def test_schema_does_not_mark_host_as_secret(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/schema").get_json()
    fields = {f["name"]: f for f in data["sources"]["kodi"]}
    assert fields["host"]["secret"] is False


# ---------------------------------------------------------------------------
# /api/config (GET)
# ---------------------------------------------------------------------------

def test_get_config_returns_current_values(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/config").get_json()
    assert data["values"]["sources.kodi.host"] == "192.168.1.21"
    assert data["values"]["general.poll_interval_seconds"] == 5


def test_get_config_returns_raw_yaml(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/config").get_json()
    assert "sources:" in data["raw_yaml"]


def test_get_config_uses_defaults_for_unconfigured_type(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/config").get_json()
    # discogs is not present in config.example.yaml
    assert data["values"]["enrichers.discogs.enabled"] is False


# ---------------------------------------------------------------------------
# /api/config (GET): outputs (multi-instance)
# ---------------------------------------------------------------------------

def test_get_config_outputs_single_instance_as_list_of_one(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/config").get_json()
    assert len(data["outputs"]["web"]) == 1
    assert data["outputs"]["web"][0]["port"] == 8090


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
    data = out.app.test_client().get("/api/config").get_json()
    ips = [inst["device_ip"] for inst in data["outputs"]["ulanzi"]]
    assert ips == ["1.1.1.1", "2.2.2.2"]


def test_get_config_outputs_unconfigured_type_has_one_default_instance(config_path):
    config_path.write_text("poll_interval_seconds: 5\n")  # no outputs section at all
    out = _output(config_path)
    data = out.app.test_client().get("/api/config").get_json()
    assert len(data["outputs"]["web"]) == 1
    assert data["outputs"]["web"][0]["enabled"] is False  # default


# ---------------------------------------------------------------------------
# /api/config/form (POST)
# ---------------------------------------------------------------------------

def test_save_form_updates_value(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    resp = client.post("/api/config/form", json={"values": {"sources.kodi.host": "10.0.0.99"}})
    assert resp.get_json() == {"ok": True}

    cfg = Config.load(config_path)
    assert cfg.sources["kodi"].host == "10.0.0.99"


def test_save_form_updates_general_field(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    client.post("/api/config/form", json={"values": {"general.poll_interval_seconds": 42}})

    cfg = Config.load(config_path)
    assert cfg.poll_interval_seconds == 42


def test_schema_includes_cache_section(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/schema").get_json()
    field_names = {f["name"] for f in data["cache"]}
    assert "min_width" in field_names
    assert "min_height" in field_names
    assert "dir" in field_names


def test_get_values_includes_cache_fields(config_path):
    out = _output(config_path)
    values = out.app.test_client().get("/api/config").get_json()["values"]
    assert values["cache.min_width"] == 640
    assert values["cache.min_height"] == 480


def test_save_form_updates_cache_min_width(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    client.post("/api/config/form", json={"values": {"cache.min_width": 320, "cache.min_height": 240}})

    cfg = Config.load(config_path)
    assert cfg.cache.min_width == 320
    assert cfg.cache.min_height == 240


def test_save_form_updates_cache_preserves_other_cache_fields(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    client.post("/api/config/form", json={"values": {"cache.min_width": 100}})

    cfg = Config.load(config_path)
    assert cfg.cache.min_width == 100
    assert cfg.cache.max_age_days == 30  # untouched, kept its existing value


def test_save_form_preserves_untouched_fields(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    client.post("/api/config/form", json={"values": {"sources.kodi.host": "10.0.0.99"}})

    cfg = Config.load(config_path)
    assert cfg.enrichers["fanarttv"].api_key == "YOUR_FANART_TV_API_KEY"
    assert cfg.sources["kodi"].port == 8080


def test_save_form_preserves_comments(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    client.post("/api/config/form", json={"values": {"sources.kodi.host": "10.0.0.99"}})

    text = config_path.read_text()
    assert "# Copy this file to config.yaml" in text


def test_save_form_sets_simple_list_field(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    client.post(
        "/api/config/form",
        json={"values": {"sources.sonos.speaker_ips": ["192.168.1.10", "192.168.1.11"]}},
    )

    cfg = Config.load(config_path)
    assert cfg.sources["sonos"].speaker_ips == ["192.168.1.10", "192.168.1.11"]


def test_get_values_returns_simple_list_field(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    client.post(
        "/api/config/form",
        json={"values": {"sources.sonos.blacklist": ["Bedroom"]}},
    )

    values = client.get("/api/config").get_json()["values"]
    assert values["sources.sonos.blacklist"] == ["Bedroom"]


def test_save_form_sets_bool_field(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    client.post("/api/config/form", json={"values": {"sources.plex.enabled": False}})

    cfg = Config.load(config_path)
    assert cfg.sources["plex"].enabled is False


def test_save_form_creates_new_section_for_unconfigured_type(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    resp = client.post(
        "/api/config/form",
        json={"values": {"enrichers.discogs.enabled": True, "enrichers.discogs.token": "abc123"}},
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
    client = out.app.test_client()
    client.post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "web": [
                    {"enabled": True, "port": 8090, "transition_exclude": ["zoom", "fade"]},
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
    client = out.app.test_client()
    client.post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "ulanzi": [
                    {"enabled": True, "device_ip": "9.9.9.9", "app_name": "now_playing"},
                    {"enabled": True, "device_ip": "2.2.2.2", "app_name": "now_playing"},
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
    client = out.app.test_client()
    client.post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "ulanzi": [
                    {"enabled": True, "device_ip": "1.1.1.1", "app_name": "now_playing"},
                    {"enabled": True, "device_ip": "2.2.2.2", "app_name": "now_playing_2"},
                ]
            },
        },
    )

    cfg = Config.load(config_path)
    ips = [c.device_ip for c in cfg.outputs["ulanzi"]]
    assert ips == ["1.1.1.1", "2.2.2.2"]


def test_save_form_appended_instance_loads_correctly_despite_trailing_comment(config_path):
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
    port: 8090
"""
    )
    out = _output(config_path)
    client = out.app.test_client()
    resp = client.post(
        "/api/config/form",
        json={
            "values": {},
            "outputs": {
                "ulanzi": [
                    {"enabled": True, "device_ip": "1.1.1.1", "app_name": "now_playing"},
                    {"enabled": True, "device_ip": "2.2.2.2", "app_name": "now_playing_2"},
                ]
            },
        },
    )
    assert resp.get_json() == {"ok": True}

    cfg = Config.load(config_path)
    ips = [c.device_ip for c in cfg.outputs["ulanzi"]]
    assert ips == ["1.1.1.1", "2.2.2.2"]
    assert cfg.outputs["web"][0].port == 8090


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
    client = out.app.test_client()
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
    client = out.app.test_client()
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
    client = out.app.test_client()
    client.post("/api/config/form", json={"values": {}, "outputs": {"ulanzi": []}})

    cfg = Config.load(config_path)
    assert cfg.outputs["ulanzi"] == []


def test_save_form_rejects_unknown_category(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    resp = client.post("/api/config/form", json={"values": {"bogus.kodi.host": "x"}})
    assert resp.get_json() == {"ok": True}  # unknown keys are silently ignored, not an error

    cfg = Config.load(config_path)
    assert cfg.sources["kodi"].host == "192.168.1.21"  # unchanged


def test_save_form_empty_values_is_noop(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    resp = client.post("/api/config/form", json={"values": {}})
    assert resp.get_json() == {"ok": True}


# ---------------------------------------------------------------------------
# /api/config/raw (POST)
# ---------------------------------------------------------------------------

def test_save_raw_writes_valid_yaml(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    new_yaml = "poll_interval_seconds: 7\nrotation_interval_seconds: 30\npriority: []\n"
    resp = client.post("/api/config/raw", json={"yaml": new_yaml})
    assert resp.get_json() == {"ok": True}
    assert config_path.read_text() == new_yaml


def test_save_raw_rejects_invalid_yaml(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    original = config_path.read_text()
    resp = client.post("/api/config/raw", json={"yaml": "not: [valid"})
    data = resp.get_json()
    assert data["ok"] is False
    assert "error" in data
    assert config_path.read_text() == original  # unchanged on failure


def test_save_raw_rejects_malformed_source_section(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    original = config_path.read_text()
    # "sources.kodi" must be a mapping; a list breaks the `**values` expansion in Config.from_dict.
    resp = client.post(
        "/api/config/raw",
        json={"yaml": "sources:\n  kodi:\n    - enabled\n    - true\n"},
    )
    assert resp.get_json()["ok"] is False
    assert config_path.read_text() == original


# ---------------------------------------------------------------------------
# /api/restart
# ---------------------------------------------------------------------------

@patch("mediainfo.outputs.config_ui.threading.Timer")
def test_restart_endpoint_schedules_restart_without_blocking(mock_timer_cls, config_path):
    out = _output(config_path)
    client = out.app.test_client()

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
    resp = out.app.test_client().get("/api/hitster-safe")
    assert resp.get_json() == {"enabled": False}


def test_hitster_safe_status_reflects_get_handler(config_path):
    out = _output(config_path)
    out.set_hitster_safe_handlers(lambda: True, MagicMock())
    resp = out.app.test_client().get("/api/hitster-safe")
    assert resp.get_json() == {"enabled": True}


def test_hitster_safe_toggle_calls_set_handler(config_path):
    out = _output(config_path)
    set_fn = MagicMock()
    out.set_hitster_safe_handlers(lambda: False, set_fn)

    resp = out.app.test_client().post(
        "/api/hitster-safe", json={"enabled": True},
    )

    assert resp.get_json() == {"enabled": True}
    set_fn.assert_called_once_with(True)


def test_hitster_safe_toggle_unavailable_when_unwired(config_path):
    out = _output(config_path)
    resp = out.app.test_client().post("/api/hitster-safe", json={"enabled": True})
    assert resp.status_code == 503


def test_hitster_safe_button_present_on_form_and_dashboard_pages(config_path):
    out = _output(config_path)
    client = out.app.test_client()
    assert b"hitster-safe-btn" in client.get("/form").data
    assert b"hitster-safe-btn" in client.get("/dashboard").data


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
    client = out.app.test_client()
    resp = client.post("/api/appletv/pair/start", json={"host": "192.168.1.90", "protocol": "companion"})

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
    client = out.app.test_client()
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
    client = out.app.test_client()
    resp = client.post("/api/appletv/pair/start", json={"host": "", "protocol": "companion"})

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    mock_scan.assert_not_called()


@patch("pyatv.scan")
def test_pair_start_no_device_found(mock_scan, config_path):
    mock_scan.return_value = []

    out = _output(config_path)
    client = out.app.test_client()
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
    client = out.app.test_client()
    resp = client.post("/api/appletv/pair/start", json={"host": "192.168.1.90", "protocol": "bogus"})

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    mock_pair.assert_not_called()


@patch("pyatv.pair")
@patch("pyatv.scan")
def test_pair_start_rejects_concurrent_attempt(mock_scan, mock_pair, config_path):
    mock_scan.return_value = [_fake_scan_result()]
    mock_pair.return_value = _fake_pairing_handler()

    out = _output(config_path)
    client = out.app.test_client()
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
    client = out.app.test_client()
    client.post("/api/appletv/pair/start", json={"host": "192.168.1.90", "protocol": "companion"})
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
    client = out.app.test_client()
    client.post("/api/appletv/pair/start", json={"host": "192.168.1.90"})
    resp = client.post("/api/appletv/pair/finish", json={})

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


@patch("pyatv.pair")
@patch("pyatv.scan")
def test_pair_finish_with_manual_pin_does_not_require_pin_in_request(mock_scan, mock_pair, config_path):
    mock_scan.return_value = [_fake_scan_result()]
    handler = _fake_pairing_handler(device_provides_pin=False, has_paired=True, credentials="xyz")
    mock_pair.return_value = handler

    out = _output(config_path)
    client = out.app.test_client()
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
    client = out.app.test_client()
    client.post("/api/appletv/pair/start", json={"host": "192.168.1.90"})
    resp = client.post("/api/appletv/pair/finish", json={"pin": "1111"})

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    handler.close.assert_awaited()


def test_pair_finish_without_start_fails(config_path):
    out = _output(config_path)
    client = out.app.test_client()
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
    client = out.app.test_client()
    client.post("/api/appletv/pair/start", json={"host": "192.168.1.90"})
    cancel_resp = client.post("/api/appletv/pair/cancel")
    restart_resp = client.post("/api/appletv/pair/start", json={"host": "192.168.1.90"})

    assert cancel_resp.get_json() == {"ok": True}
    assert restart_resp.get_json()["ok"] is True
    handler.close.assert_awaited()


def test_pair_cancel_with_no_session_is_noop(config_path):
    out = _output(config_path)
    client = out.app.test_client()
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
    out = _output(config_path)
    resp = out.app.test_client().get("/")
    assert resp.status_code == 200
    assert b"configuration" in resp.data


# ---------------------------------------------------------------------------
# library page and /api/library/*
# ---------------------------------------------------------------------------

def test_library_page_served(library_config_path):
    out = _output(library_config_path)
    resp = out.app.test_client().get("/library")
    assert resp.status_code == 200
    assert b"library" in resp.data.lower()


def test_library_stats_empty(library_config_path):
    out = _output(library_config_path)
    resp = out.app.test_client().get("/api/library/stats")
    assert resp.get_json() == {"artists": 0, "albums": 0, "tracks": 0}


def test_library_stats_counts_seeded_data(library_config_path):
    out = _output(library_config_path)
    library = out._get_library()
    artist_id = library.get_or_create_artist("Pink Floyd")
    library.get_or_create_album(artist_id, "The Wall")
    library.get_or_create_track(artist_id, "Money")

    resp = out.app.test_client().get("/api/library/stats")
    assert resp.get_json() == {"artists": 1, "albums": 1, "tracks": 1}


def test_library_search_empty_query_returns_empty_list(library_config_path):
    out = _output(library_config_path)
    resp = out.app.test_client().get("/api/library/search")
    assert resp.get_json() == []


def test_library_search_returns_matching_artists(library_config_path):
    out = _output(library_config_path)
    library = out._get_library()
    library.get_or_create_artist("Pink Floyd")
    library.get_or_create_artist("Queen")

    resp = out.app.test_client().get("/api/library/search?q=pink")
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["name"] == "Pink Floyd"
    assert isinstance(data[0]["id"], int)


def test_library_search_is_fuzzy(library_config_path):
    out = _output(library_config_path)
    library = out._get_library()
    library.get_or_create_artist("Simon & Garfunkel")

    resp = out.app.test_client().get("/api/library/search?q=simon and garfunkel")
    assert [a["name"] for a in resp.get_json()] == ["Simon & Garfunkel"]


def test_library_artist_returns_albums_and_tracks(library_config_path):
    out = _output(library_config_path)
    library = out._get_library()
    artist_id = library.get_or_create_artist("Pink Floyd")
    library.set_mbid("artist", artist_id, "artist-mbid")
    album_id = library.get_or_create_album(artist_id, "The Wall")
    library.set_mbid("album", album_id, "album-mbid")
    library.get_or_create_track(artist_id, "Money")

    resp = out.app.test_client().get(f"/api/library/artist/{artist_id}")
    data = resp.get_json()
    assert data["name"] == "Pink Floyd"
    assert data["mbid"] == "artist-mbid"
    assert data["albums"] == [{"id": album_id, "title": "The Wall", "mbid": "album-mbid"}]
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["title"] == "Money"


def test_library_artist_not_found_returns_404(library_config_path):
    out = _output(library_config_path)
    resp = out.app.test_client().get("/api/library/artist/999")
    assert resp.status_code == 404


def test_get_library_reuses_connection_across_requests(library_config_path):
    out = _output(library_config_path)
    lib1 = out._get_library()
    lib2 = out._get_library()
    assert lib1 is lib2


# ---------------------------------------------------------------------------
# Optional auth (config.yaml's config has write access to credentials, so
# this is the highest-value place for it - see web_auth.py)
# ---------------------------------------------------------------------------

def test_auth_disabled_by_default(config_path):
    from mediainfo.outputs.config_ui import ConfigUiOutput
    out = ConfigUiOutput(_config(), config_path)
    resp = out.app.test_client().get("/", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
    assert resp.status_code == 200


def test_auth_required_for_public_address_when_enabled(config_path):
    from mediainfo.config import AuthConfig
    from mediainfo.outputs.config_ui import ConfigUiOutput
    auth = AuthConfig(enabled=True, username="admin", password="secret")
    out = ConfigUiOutput(_config(), config_path, auth)
    resp = out.app.test_client().get("/", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
    assert resp.status_code == 401


def test_auth_not_required_for_private_address_when_enabled(config_path):
    from mediainfo.config import AuthConfig
    from mediainfo.outputs.config_ui import ConfigUiOutput
    auth = AuthConfig(enabled=True, username="admin", password="secret")
    out = ConfigUiOutput(_config(), config_path, auth)
    resp = out.app.test_client().get("/", environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Dashboard UI (ui: dashboard)
# ---------------------------------------------------------------------------

def test_form_ui_is_default_index_page(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = out.app.test_client().get("/")
    assert b"configuration" in resp.data
    assert b"mediainfo status" not in resp.data


def test_dashboard_ui_serves_dashboard_page(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = out.app.test_client().get("/")
    assert resp.status_code == 200
    assert b"mediainfo status" in resp.data


def test_form_page_reachable_on_dashboard_instance(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = out.app.test_client().get("/form")
    assert resp.status_code == 200
    assert b"mediainfo configuration" in resp.data


def test_dashboard_page_reachable_on_form_instance(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = out.app.test_client().get("/dashboard")
    assert resp.status_code == 200
    assert b"mediainfo status" in resp.data


def test_form_page_links_to_dashboard(config_path):
    out = ConfigUiOutput(_config(), config_path)
    resp = out.app.test_client().get("/form")
    assert b'href="/dashboard"' in resp.data


def test_dashboard_page_links_to_form(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = out.app.test_client().get("/dashboard")
    assert b'href="/form"' in resp.data


def test_dashboard_page_has_inline_edit_controls(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = out.app.test_client().get("/dashboard")
    assert b"startEdit" in resp.data
    assert b"saveEdit" in resp.data
    assert b"editBtn.textContent = 'Edit'" in resp.data


def test_dashboard_instance_can_read_schema_and_config_for_editing(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    client = out.app.test_client()

    schema = client.get("/api/schema").get_json()
    assert "kodi" in schema["sources"]

    config = client.get("/api/config").get_json()
    assert config["values"]["sources.kodi.host"] == "192.168.1.21"


def test_dashboard_instance_can_save_form_edits(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    client = out.app.test_client()

    resp = client.post(
        "/api/config/form",
        json={"values": {"sources.kodi.host": "192.168.50.50"}},
    )
    assert resp.get_json() == {"ok": True}


def test_dashboard_page_has_restart_button(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = out.app.test_client().get("/dashboard")
    assert b"restartDashboard" in resp.data
    assert b"/api/restart" in resp.data
    assert b"Restart mediainfo" in resp.data


def test_dashboard_page_marks_failed_source_test_as_unavailable(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = out.app.test_client().get("/dashboard")
    assert b"statusOverrides[key] = 'unavailable'" in resp.data
    assert b"b-unavailable" in resp.data
    assert b'data-filter="unavailable"' in resp.data


def test_api_status_returns_empty_lists_without_health_provider(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    resp = out.app.test_client().get("/api/status")
    assert resp.get_json() == {"sources": [], "outputs": [], "enrichers": []}


def test_api_status_returns_health_provider_data(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    out.set_health_provider(lambda: {
        "sources": [{"name": "kodi", "status": "active"}],
        "outputs": [{"type": "web", "status": "ok", "port": 8090}],
        "enrichers": [{"name": "musicbrainz", "status": "ok"}],
        "now_playing": None,
    })

    resp = out.app.test_client().get("/api/status")
    data = resp.get_json()

    assert data["sources"] == [{"name": "kodi", "status": "active"}]
    assert data["outputs"] == [{"type": "web", "status": "ok", "port": 8090}]
    assert data["enrichers"] == [{"name": "musicbrainz", "status": "ok"}]
    assert "now_playing" not in data  # only sources/outputs/enrichers are exposed


def test_api_test_source_route_dispatches(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    with patch("mediainfo.outputs.config_ui.test_source", return_value=(True, "ok")) as mock_test:
        resp = out.app.test_client().post("/api/test/source/kodi")

    assert resp.get_json() == {"ok": True, "message": "ok"}
    name_arg, config_arg = mock_test.call_args.args
    assert name_arg == "kodi"


def test_api_test_enricher_route_dispatches(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    with patch(
        "mediainfo.outputs.config_ui.test_enricher", return_value=(False, "no")
    ) as mock_test:
        resp = out.app.test_client().post("/api/test/enricher/thetvdb")

    assert resp.get_json() == {"ok": False, "message": "no"}
    name_arg, _ = mock_test.call_args.args
    assert name_arg == "thetvdb"


def test_api_test_output_route_dispatches(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    with patch(
        "mediainfo.outputs.config_ui.test_output", return_value=(True, "reached")
    ) as mock_test:
        resp = out.app.test_client().post(
            "/api/test/output",
            json={"type": "pixoo", "ip": "192.168.1.32"},
        )

    assert resp.get_json() == {"ok": True, "message": "reached"}
    mock_test.assert_called_once_with("pixoo", {"type": "pixoo", "ip": "192.168.1.32"})


def test_api_test_output_route_handles_missing_body(config_path):
    out = ConfigUiOutput(_config(ui="dashboard"), config_path)
    with patch(
        "mediainfo.outputs.config_ui.test_output", return_value=(False, "No connection test")
    ):
        resp = out.app.test_client().post("/api/test/output")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# Artwork overrides
# ---------------------------------------------------------------------------

def test_overrides_page_served(config_path):
    out = _output(config_path)
    resp = out.app.test_client().get("/overrides")
    assert resp.status_code == 200
    assert b"overrides" in resp.data.lower()


def test_overrides_list_reports_disabled_when_no_store_registered(config_path):
    out = _output(config_path)
    resp = out.app.test_client().get("/api/overrides")
    assert resp.get_json() == {"enabled": False, "items": []}


def test_overrides_list_empty_when_enabled(config_path, tmp_path):
    from mediainfo.artwork_overrides import ArtworkOverrideStore

    out = _output(config_path)
    out.set_artwork_overrides(ArtworkOverrideStore(str(tmp_path / "overrides")))

    resp = out.app.test_client().get("/api/overrides")

    assert resp.get_json() == {"enabled": True, "items": []}


def test_overrides_add_then_list(config_path, tmp_path):
    import io

    from mediainfo.artwork_overrides import ArtworkOverrideStore

    out = _output(config_path)
    out.set_artwork_overrides(ArtworkOverrideStore(str(tmp_path / "overrides")))

    resp = out.app.test_client().post(
        "/api/overrides",
        data={
            "title": "Inception",
            "subtitle": "",
            "file": (io.BytesIO(b"fake-image-bytes"), "poster.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert resp.get_json() == {"ok": True}

    listed = out.app.test_client().get("/api/overrides").get_json()
    assert listed["enabled"] is True
    assert len(listed["items"]) == 1
    assert listed["items"][0]["title"] == "Inception"


def test_overrides_add_without_title_is_rejected(config_path, tmp_path):
    import io

    from mediainfo.artwork_overrides import ArtworkOverrideStore

    out = _output(config_path)
    out.set_artwork_overrides(ArtworkOverrideStore(str(tmp_path / "overrides")))

    resp = out.app.test_client().post(
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

    resp = out.app.test_client().post(
        "/api/overrides", data={"title": "Inception"}, content_type="multipart/form-data",
    )

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_overrides_add_when_disabled_returns_503(config_path):
    import io

    out = _output(config_path)
    resp = out.app.test_client().post(
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
    out.app.test_client().post(
        "/api/overrides",
        data={"title": "Inception", "file": (io.BytesIO(b"x"), "poster.jpg")},
        content_type="multipart/form-data",
    )

    resp = out.app.test_client().delete(
        "/api/overrides", json={"title": "Inception", "subtitle": ""},
    )

    assert resp.get_json() == {"ok": True}
    assert out.app.test_client().get("/api/overrides").get_json()["items"] == []


def test_overrides_remove_when_disabled_returns_503(config_path):
    out = _output(config_path)
    resp = out.app.test_client().delete("/api/overrides", json={"title": "Inception"})
    assert resp.status_code == 503


def test_overrides_image_served(config_path, tmp_path):
    import io

    from mediainfo.artwork_overrides import ArtworkOverrideStore

    out = _output(config_path)
    out.set_artwork_overrides(ArtworkOverrideStore(str(tmp_path / "overrides")))
    out.app.test_client().post(
        "/api/overrides",
        data={"title": "Inception", "file": (io.BytesIO(b"fake-image-bytes"), "poster.jpg")},
        content_type="multipart/form-data",
    )
    filename = out.app.test_client().get("/api/overrides").get_json()["items"][0]["filename"]

    resp = out.app.test_client().get(f"/api/overrides/image/{filename}")

    assert resp.status_code == 200
    assert resp.data == b"fake-image-bytes"


def test_overrides_image_rejects_path_traversal(config_path, tmp_path):
    from mediainfo.artwork_overrides import ArtworkOverrideStore

    out = _output(config_path)
    out.set_artwork_overrides(ArtworkOverrideStore(str(tmp_path / "overrides")))

    resp = out.app.test_client().get("/api/overrides/image/..%2F..%2Fetc%2Fpasswd")

    assert resp.status_code == 404


def test_overrides_image_404_when_disabled(config_path):
    out = _output(config_path)
    resp = out.app.test_client().get("/api/overrides/image/whatever.jpg")
    assert resp.status_code == 404
