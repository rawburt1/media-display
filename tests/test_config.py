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
    assert config.priority == [
        "kodi", "appletv", "homeassistant", "youtube", "shield", "plex", "sonos", "spotify", "vinyl",
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
    assert config.priority == []
    assert config.sources == {}
    assert config.outputs == {}


def test_from_dict_raises_on_unknown_field():
    with pytest.raises(TypeError):
        Config.from_dict({"sources": {"kodi": {"enabled": True, "no_such_field": "x"}}})
