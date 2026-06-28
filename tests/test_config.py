"""Tests for Config.load."""

from pathlib import Path

import pytest

from mediainfo.config import Config, WebConfig

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


def test_load_example_config():
    config = Config.load(EXAMPLE_CONFIG)

    assert config.poll_interval_seconds == 5
    assert config.rotation_interval_seconds == 30
    assert config.backoff_initial_seconds == 30
    assert config.backoff_max_seconds == 300
    assert config.nothing_playing_grace_seconds == 2
    assert config.priority == [
        "kodi", "appletv", "homeassistant", "youtube", "shield", "plex", "sonos", "spotify", "vinyl",
        "ps5", "chromecast",
    ]

    assert config.sources["kodi"].enabled is True
    assert config.sources["kodi"].host == "192.168.1.21"
    assert config.sources["sonos"].speaker_ips == ["192.168.1.80", "192.168.1.81"]

    assert config.sources["shield"].enabled is True
    assert config.sources["shield"].host == "192.168.1.21"
    assert config.sources["shield"].port == 5555
    assert config.sources["shield"].adb_key_path == "./adb_keys/shield"

    assert config.sources["plex"].enabled is True
    assert config.sources["plex"].host == "192.168.1.22"
    assert config.sources["plex"].port == 32400
    assert config.sources["plex"].token == "YOUR_PLEX_TOKEN"

    assert config.sources["vinyl"].enabled is True
    assert config.sources["vinyl"].host == "192.168.1.40"
    assert config.sources["vinyl"].port == 8091

    assert config.outputs["pixoo"][0].ip == "192.168.1.32"
    assert config.outputs["web"][0].port == 8090
    assert config.outputs["folder"][0].enabled is True
    assert config.outputs["folder"][0].dir == "./artwork"

    assert config.enrichers["fanarttv"].enabled is True
    assert config.enrichers["fanarttv"].api_key == "YOUR_FANART_TV_API_KEY"

    assert config.cache.dir == "./cache"
    assert config.cache.max_age_days == 30

    assert config.library.db_path == "./library/library.db"
    assert config.library.max_age_days == 30

    assert config.auth.enabled is False
    assert config.auth.username == "YOUR_USERNAME"
    assert config.auth.password == "YOUR_PASSWORD"


def test_load_missing_file_raises(tmp_path):
    missing = tmp_path / "does-not-exist.yaml"
    with pytest.raises(FileNotFoundError):
        Config.load(missing)


def test_output_type_accepts_a_list_for_multiple_instances(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
outputs:
  ulanzi:
    - enabled: true
      device_ip: 192.168.1.30
      app_name: now_playing
    - enabled: true
      device_ip: 192.168.1.31
      app_name: now_playing_bedroom
  web:
    enabled: true
    port: 8090
"""
    )

    config = Config.load(config_path)

    assert [u.device_ip for u in config.outputs["ulanzi"]] == ["192.168.1.30", "192.168.1.31"]
    assert config.outputs["ulanzi"][1].app_name == "now_playing_bedroom"
    assert config.outputs["web"] == [WebConfig(enabled=True, port=8090)]


# ---------------------------------------------------------------------------
# Config.from_dict
# ---------------------------------------------------------------------------

def test_from_dict_builds_equivalent_config_to_load(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("poll_interval_seconds: 9\nsources:\n  kodi:\n    enabled: true\n    host: 1.2.3.4\n")

    via_load = Config.load(config_path)
    via_dict = Config.from_dict(
        {"poll_interval_seconds": 9, "sources": {"kodi": {"enabled": True, "host": "1.2.3.4"}}}
    )

    assert via_load.poll_interval_seconds == via_dict.poll_interval_seconds == 9
    assert via_load.sources["kodi"].host == via_dict.sources["kodi"].host == "1.2.3.4"


def test_from_dict_empty_dict_uses_defaults():
    config = Config.from_dict({})
    assert config.poll_interval_seconds == 5
    assert config.rotation_interval_seconds == 30
    assert config.backoff_initial_seconds == 30
    assert config.backoff_max_seconds == 300
    assert config.nothing_playing_grace_seconds == 2
    assert config.priority == []
    assert config.sources == {}
    assert config.outputs == {}


def test_from_dict_raises_on_unknown_field():
    with pytest.raises(TypeError):
        Config.from_dict({"sources": {"kodi": {"enabled": True, "no_such_field": "x"}}})


# ---------------------------------------------------------------------------
# Unknown plugin name warnings
# ---------------------------------------------------------------------------

def test_from_dict_warns_on_unknown_source_name(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="mediainfo.config"):
        Config.from_dict({"sources": {"youtubee": {"enabled": True, "host": "1.2.3.4"}}})
    assert any("youtubee" in r.message for r in caplog.records)


def test_from_dict_warns_on_unknown_output_name(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="mediainfo.config"):
        Config.from_dict({"outputs": {"webb": {"enabled": True}}})
    assert any("webb" in r.message for r in caplog.records)


def test_from_dict_warns_on_unknown_enricher_name(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="mediainfo.config"):
        Config.from_dict({"enrichers": {"fanartv": {"enabled": True, "api_key": "x"}}})
    assert any("fanartv" in r.message for r in caplog.records)


def test_from_dict_warns_on_unknown_idle_name(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="mediainfo.config"):
        Config.from_dict({"idle": {"unsplashh": {"enabled": True, "access_key": "x"}}})
    assert any("unsplashh" in r.message for r in caplog.records)


def test_from_dict_does_not_warn_on_known_plugin_names(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="mediainfo.config"):
        Config.from_dict({"sources": {"kodi": {"enabled": True}}, "outputs": {"web": {"enabled": True}}})
    assert caplog.records == []


# ---------------------------------------------------------------------------
# ConfigUiConfig host default
# ---------------------------------------------------------------------------

def test_config_ui_config_default_host_is_loopback():
    from mediainfo.config import ConfigUiConfig
    cfg = ConfigUiConfig()
    assert cfg.host == "127.0.0.1"


def test_web_config_default_host_is_any():
    from mediainfo.config import WebConfig
    cfg = WebConfig()
    assert cfg.host == "0.0.0.0"


# ---------------------------------------------------------------------------
# Environment variable expansion
# ---------------------------------------------------------------------------

def test_load_expands_env_var_in_string_value(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_PLEX_TOKEN", "secret-token-123")
    p = tmp_path / "config.yaml"
    p.write_text("sources:\n  plex:\n    enabled: true\n    token: ${TEST_PLEX_TOKEN}\n")
    config = Config.load(p)
    assert config.sources["plex"].token == "secret-token-123"


def test_load_expands_env_var_with_default(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_MISSING_VAR", raising=False)
    p = tmp_path / "config.yaml"
    p.write_text("sources:\n  plex:\n    enabled: true\n    token: ${TEST_MISSING_VAR:-fallback}\n")
    config = Config.load(p)
    assert config.sources["plex"].token == "fallback"


def test_load_keeps_literal_when_env_var_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_MISSING_VAR", raising=False)
    p = tmp_path / "config.yaml"
    p.write_text("sources:\n  plex:\n    enabled: true\n    token: ${TEST_MISSING_VAR}\n")
    config = Config.load(p)
    assert config.sources["plex"].token == "${TEST_MISSING_VAR}"


def test_load_does_not_expand_non_env_var_strings(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("sources:\n  kodi:\n    enabled: true\n    host: 192.168.1.21\n")
    config = Config.load(p)
    assert config.sources["kodi"].host == "192.168.1.21"
