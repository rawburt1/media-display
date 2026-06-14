"""Tests for Config.load."""

from pathlib import Path

import pytest

from pixoo_media.config import Config

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


def test_load_example_config():
    config = Config.load(EXAMPLE_CONFIG)

    assert config.poll_interval_seconds == 5
    assert config.rotation_interval_seconds == 30
    assert config.priority == ["kodi", "sonos"]

    assert config.sources["kodi"].enabled is True
    assert config.sources["kodi"].host == "192.168.1.21"
    assert config.sources["sonos"].speaker_ip == "192.168.1.80"

    assert config.outputs["pixoo"].ip == "192.168.1.32"
    assert config.outputs["web"].port == 8090

    assert config.enrichers["fanarttv"].enabled is True
    assert config.enrichers["fanarttv"].api_key == "YOUR_FANART_TV_API_KEY"

    assert config.cache.dir == "./cache"


def test_load_missing_file_raises(tmp_path):
    missing = tmp_path / "does-not-exist.yaml"
    with pytest.raises(FileNotFoundError):
        Config.load(missing)
