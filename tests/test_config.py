"""Tests for Config.load."""

from pathlib import Path

import pytest

from pixoo_media.config import Config, WebConfig

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


def test_load_example_config():
    config = Config.load(EXAMPLE_CONFIG)

    assert config.poll_interval_seconds == 5
    assert config.rotation_interval_seconds == 30
    assert config.priority == ["kodi", "appletv", "shield", "plex", "sonos", "spotify", "vinyl"]

    assert config.sources["kodi"].enabled is True
    assert config.sources["kodi"].host == "192.168.1.21"
    assert config.sources["sonos"].speaker_ip == "192.168.1.80"

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
