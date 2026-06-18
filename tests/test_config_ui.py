"""Tests for the config output (web UI for editing config.yaml)."""

import shutil
from pathlib import Path

import pytest

from mediainfo.config import Config, ConfigUiConfig
from mediainfo.outputs.config_ui import ConfigUiOutput

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


@pytest.fixture(autouse=True)
def no_server(monkeypatch):
    monkeypatch.setattr("threading.Thread.start", lambda self: None)


def _config(**kwargs):
    return ConfigUiConfig(enabled=True, host="127.0.0.1", port=8094, **kwargs)


def _output(config_path):
    return ConfigUiOutput(_config(), config_path)


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    shutil.copy(EXAMPLE_CONFIG, path)
    return path


# ---------------------------------------------------------------------------
# /api/schema
# ---------------------------------------------------------------------------

def test_schema_includes_all_categories(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/schema").get_json()
    assert set(data.keys()) == {"general", "sources", "outputs", "enrichers", "idle"}


def test_schema_includes_known_source_types(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/schema").get_json()
    assert "kodi" in data["sources"]
    assert "plex" in data["sources"]


def test_schema_excludes_list_typed_fields(config_path):
    out = _output(config_path)
    data = out.app.test_client().get("/api/schema").get_json()
    field_names = {f["name"] for f in data["sources"]["sonos"]}
    assert "blacklist" not in field_names
    assert "speaker_ip" in field_names


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


def test_save_form_updates_first_instance_of_list_output(config_path):
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
    client.post("/api/config/form", json={"values": {"outputs.ulanzi.device_ip": "9.9.9.9"}})

    cfg = Config.load(config_path)
    ips = [c.device_ip for c in cfg.outputs["ulanzi"]]
    assert ips == ["9.9.9.9", "2.2.2.2"]


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
