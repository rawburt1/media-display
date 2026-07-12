"""Smoke test: build the whole app from config.example.yaml - the same
build_sources/build_enrichers/build_idle_source/instantiate_outputs calls
__main__.main() makes - with network access and background threads
mocked out, and confirm every plugin enabled in that file actually
constructs without raising.

This catches a class of mistake the registry-completeness tests
(test_registries.py) can't: a plugin registered correctly in both
registries, but whose constructor signature (or an import) is broken, so
building the real example config blows up the moment it's used for real.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mediainfo import wiring
from mediainfo.cache import ImageCache
from mediainfo.config import Config

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    # Suppress every output's background Flask/server thread (web, info,
    # video, config, feed, nest_hub) and AppleTvSource's pyatv-loop thread.
    monkeypatch.setattr("threading.Thread.start", lambda self: None)
    # Avoid real RSA key generation/loading for the ADB-based sources.
    monkeypatch.setattr(
        "mediainfo.sources.shield.ShieldSource._load_or_create_signer",
        lambda self, path: MagicMock(),
    )
    monkeypatch.setattr(
        "mediainfo.sources.youtube.YoutubeSource._load_or_create_signer",
        lambda self, path: MagicMock(),
    )
    # Avoid a real MQTT broker connection attempt.
    monkeypatch.setattr("mediainfo.outputs.mqtt.mqtt.Client", MagicMock())


@pytest.fixture
def example_config(tmp_path):
    config = Config.load(EXAMPLE_CONFIG)

    # Redirect every path the example config points at (relative to the
    # repo root) into tmp_path, so this test never touches real files.
    config.cache.dir = str(tmp_path / "cache")
    config.library.db_path = str(tmp_path / "library.db")
    for folder_cfg in config.outputs.get("folder", []):
        folder_cfg.dir = str(tmp_path / "artwork")
    config.sources["shield"].adb_key_path = str(tmp_path / "shield_key")
    config.sources["youtube"].adb_key_path = str(tmp_path / "youtube_key")
    config.sources["spotify"].cache_path = str(tmp_path / "spotify_token.json")

    return config


def test_build_sources_from_example_config(example_config):
    sources = wiring.build_sources(example_config)
    names = {s.name for s in sources}
    assert names == {
        "kodi",
        "appletv",
        "homeassistant",
        "youtube",
        "shield",
        "plex",
        "sonos",
        "spotify",
        "mopidy",
        "mpd",
        "lms",
        "foobar2000",
        "vlc",
        "vinyl",
        "browser",
        "chromecast",
    }


def test_build_enrichers_from_example_config(example_config):
    enrichers = wiring.build_enrichers(example_config)
    # Every enabled enricher in config.example.yaml.
    assert len(enrichers) == 12


def test_build_idle_source_from_example_config(example_config):
    idle_source = wiring.build_idle_source(example_config)
    assert idle_source is not None


def test_instantiate_outputs_from_example_config(example_config, tmp_path):
    cache = ImageCache(example_config.cache.dir)
    outputs = wiring.instantiate_outputs(example_config, tmp_path / "config.yaml", cache)
    # Every enabled output type in config.example.yaml (one instance each).
    assert len(outputs) == 10


def test_full_wiring_from_example_config(example_config, tmp_path):
    """End-to-end: build everything __main__.main() builds before starting
    the orchestrator loop, all from the one config file new users copy.
    """
    cache = ImageCache(example_config.cache.dir)
    outputs = wiring.instantiate_outputs(example_config, tmp_path / "config.yaml", cache)
    sources = wiring.build_sources(example_config)
    enrichers = wiring.build_enrichers(example_config)
    idle_source = wiring.build_idle_source(example_config)

    assert outputs
    assert sources
    assert enrichers
    assert idle_source is not None
