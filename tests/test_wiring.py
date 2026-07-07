"""Tests for mediainfo.wiring: building sources/enrichers/idle sources/
outputs from config, and wiring cross-cutting state onto outputs.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from mediainfo.text_cache import TextCache
from mediainfo.wiring import (
    build_artwork_overrides,
    build_enrichers,
    build_idle_source,
    build_mediadata_store,
    build_sources,
    build_text_enrichers,
    instantiate_outputs,
    start_orchestrator,
    wire_artwork_overrides,
    wire_artwork_refresh,
    wire_health_providers,
    wire_hitster_safe,
    wire_rotate_now,
)


def _minimal_config(**kwargs):
    """Return a MagicMock that quacks like a Config."""
    cfg = MagicMock()
    cfg.priority = []
    cfg.sources = {}
    cfg.enrichers = {}
    cfg.text_enrichers = {}
    cfg.idle = {}
    cfg.idle_priority = []
    cfg.idle_mode = "priority"
    # Real values (not a bare MagicMock attribute) - build_text_enrichers()
    # constructs a real TextCache(Path(config.cache.dir)/"text", ...),
    # which creates that directory on disk; a MagicMock-derived path would
    # otherwise get mkdir'd for real under a garbage name.
    cfg.cache.dir = tempfile.gettempdir()
    cfg.cache.max_age_days = 30
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


# ---------------------------------------------------------------------------
# instantiate_outputs
# ---------------------------------------------------------------------------

def test_instantiate_outputs_calls_start_on_each():
    output_cfg = MagicMock()
    output_cfg.enabled = True
    fake_instance = MagicMock()
    fake_cls = MagicMock(return_value=fake_instance)
    cfg = _minimal_config(outputs={"pixoo": [output_cfg]})

    with (
        patch("mediainfo.registries.OUTPUT_CLASSES", {"pixoo": fake_cls}),
        patch("mediainfo.registries.OUTPUT_EXTRA_ARGS", {}),
    ):
        result = instantiate_outputs(cfg, Path("config.yaml"), MagicMock())

    fake_instance.start.assert_called_once_with()
    assert result == [fake_instance]


def test_instantiate_outputs_skips_disabled():
    output_cfg = MagicMock()
    output_cfg.enabled = False
    fake_cls = MagicMock(return_value=MagicMock())
    cfg = _minimal_config(outputs={"pixoo": [output_cfg]})

    with (
        patch("mediainfo.registries.OUTPUT_CLASSES", {"pixoo": fake_cls}),
        patch("mediainfo.registries.OUTPUT_EXTRA_ARGS", {}),
    ):
        result = instantiate_outputs(cfg, Path("config.yaml"), MagicMock())

    fake_cls.assert_not_called()
    assert result == []


# ---------------------------------------------------------------------------
# build_sources / build_enrichers / build_idle_source
# ---------------------------------------------------------------------------

def test_build_sources_empty_priority():
    cfg = _minimal_config()
    assert build_sources(cfg) == []


def test_build_sources_skips_disabled():
    source_cfg = MagicMock()
    source_cfg.enabled = False
    cfg = _minimal_config(priority=["kodi"], sources={"kodi": source_cfg})
    assert build_sources(cfg) == []


def test_build_sources_skips_unknown(caplog):
    import logging

    source_cfg = MagicMock()
    source_cfg.enabled = True
    cfg = _minimal_config(priority=["nonexistent"], sources={"nonexistent": source_cfg})
    with caplog.at_level(logging.WARNING, logger="mediainfo.wiring"):
        result = build_sources(cfg)
    assert result == []
    assert any("nonexistent" in r.message for r in caplog.records)


def test_build_sources_instantiates_enabled():
    source_cfg = MagicMock()
    source_cfg.enabled = True

    fake_cls = MagicMock(return_value=MagicMock())
    cfg = _minimal_config(priority=["kodi"], sources={"kodi": source_cfg})

    with patch("mediainfo.registries.SOURCE_CLASSES", {"kodi": fake_cls}):
        result = build_sources(cfg)

    fake_cls.assert_called_once_with(source_cfg)
    assert result == [fake_cls.return_value]


def test_build_enrichers_skips_disabled():
    enc_cfg = MagicMock()
    enc_cfg.enabled = False
    cfg = _minimal_config(enrichers={"fanarttv": enc_cfg})
    assert build_enrichers(cfg) == []


def test_build_enrichers_instantiates_enabled():
    enc_cfg = MagicMock()
    enc_cfg.enabled = True

    fake_cls = MagicMock(return_value=MagicMock())
    cfg = _minimal_config(enrichers={"fanarttv": enc_cfg})

    with (
        patch("mediainfo.registries.ENRICHER_CLASSES", {"fanarttv": fake_cls}),
        patch("mediainfo.registries.LIBRARY_AWARE_ENRICHER_NAMES", set()),
    ):
        result = build_enrichers(cfg)

    fake_cls.assert_called_once_with(enc_cfg)
    assert result == [fake_cls.return_value]


def test_build_enrichers_passes_library_to_library_aware_enrichers():
    enc_cfg = MagicMock()
    enc_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    fake_library = MagicMock()
    cfg = _minimal_config(enrichers={"fanarttv": enc_cfg})

    with (
        patch("mediainfo.registries.ENRICHER_CLASSES", {"fanarttv": fake_cls}),
        patch("mediainfo.registries.LIBRARY_AWARE_ENRICHER_NAMES", {"fanarttv"}),
    ):
        result = build_enrichers(cfg, fake_library)

    fake_cls.assert_called_once_with(enc_cfg, fake_library)
    assert result == [fake_cls.return_value]


def test_build_enrichers_passes_cache_dir_to_cache_aware_enrichers():
    enc_cfg = MagicMock()
    enc_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    cfg = _minimal_config(enrichers={"ai_artwork": enc_cfg})

    with (
        patch("mediainfo.registries.ENRICHER_CLASSES", {"ai_artwork": fake_cls}),
        patch("mediainfo.registries.LIBRARY_AWARE_ENRICHER_NAMES", set()),
        patch("mediainfo.registries.CACHE_AWARE_ENRICHER_NAMES", {"ai_artwork"}),
    ):
        result = build_enrichers(cfg)

    args, _ = fake_cls.call_args
    assert args[0] is enc_cfg
    assert args[1] == Path(cfg.cache.dir) / "ai_artwork"
    assert result == [fake_cls.return_value]


def test_build_enrichers_passes_mediadata_store_to_mediadata_aware_enrichers():
    enc_cfg = MagicMock()
    enc_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    fake_store = MagicMock()
    cfg = _minimal_config(enrichers={"mediadata": enc_cfg})

    with (
        patch("mediainfo.registries.ENRICHER_CLASSES", {"mediadata": fake_cls}),
        patch("mediainfo.registries.LIBRARY_AWARE_ENRICHER_NAMES", set()),
        patch("mediainfo.registries.CACHE_AWARE_ENRICHER_NAMES", set()),
        patch("mediainfo.registries.MEDIADATA_AWARE_ENRICHER_NAMES", {"mediadata"}),
    ):
        result = build_enrichers(cfg, mediadata_store=fake_store)

    fake_cls.assert_called_once_with(enc_cfg, fake_store)
    assert result == [fake_cls.return_value]


# ---------------------------------------------------------------------------
# build_mediadata_store
# ---------------------------------------------------------------------------

def test_build_mediadata_store_none_when_neither_plugin_enabled():
    cfg = _minimal_config(enrichers={}, text_enrichers={})
    assert build_mediadata_store(cfg, MagicMock()) is None


def test_build_mediadata_store_none_when_both_disabled():
    artwork_cfg = MagicMock(enabled=False)
    lyrics_cfg = MagicMock(enabled=False)
    cfg = _minimal_config(
        enrichers={"mediadata": artwork_cfg}, text_enrichers={"mediadata": lyrics_cfg}
    )
    assert build_mediadata_store(cfg, MagicMock()) is None


def test_build_mediadata_store_constructed_when_artwork_enabled():
    artwork_cfg = MagicMock(enabled=True)
    cfg = _minimal_config(enrichers={"mediadata": artwork_cfg}, text_enrichers={})
    fake_cache = MagicMock()
    fake_cls = MagicMock(return_value=MagicMock())

    with patch("mediainfo.wiring.MediaDataStore", fake_cls):
        result = build_mediadata_store(cfg, fake_cache)

    fake_cls.assert_called_once_with(cfg.mediadata, cache=fake_cache, discogs_token="")
    assert result is fake_cls.return_value


def test_build_mediadata_store_constructed_when_lyrics_enabled():
    lyrics_cfg = MagicMock(enabled=True)
    cfg = _minimal_config(enrichers={}, text_enrichers={"mediadata": lyrics_cfg})
    fake_cls = MagicMock(return_value=MagicMock())

    with patch("mediainfo.wiring.MediaDataStore", fake_cls):
        result = build_mediadata_store(cfg, MagicMock())

    assert result is fake_cls.return_value


def test_build_mediadata_store_passes_discogs_token_when_enabled():
    artwork_cfg = MagicMock(enabled=True)
    discogs_cfg = MagicMock(enabled=True, token="secret-token")
    cfg = _minimal_config(
        enrichers={"mediadata": artwork_cfg, "discogs": discogs_cfg}, text_enrichers={}
    )
    fake_cls = MagicMock(return_value=MagicMock())

    with patch("mediainfo.wiring.MediaDataStore", fake_cls):
        build_mediadata_store(cfg, MagicMock())

    _, kwargs = fake_cls.call_args
    assert kwargs["discogs_token"] == "secret-token"


def test_build_mediadata_store_skips_discogs_token_when_disabled():
    artwork_cfg = MagicMock(enabled=True)
    discogs_cfg = MagicMock(enabled=False, token="secret-token")
    cfg = _minimal_config(
        enrichers={"mediadata": artwork_cfg, "discogs": discogs_cfg}, text_enrichers={}
    )
    fake_cls = MagicMock(return_value=MagicMock())

    with patch("mediainfo.wiring.MediaDataStore", fake_cls):
        build_mediadata_store(cfg, MagicMock())

    _, kwargs = fake_cls.call_args
    assert kwargs["discogs_token"] == ""


# ---------------------------------------------------------------------------
# build_text_enrichers (roadmap item 7 foundation - no real plugin yet)
# ---------------------------------------------------------------------------

def test_build_text_enrichers_empty_by_default():
    cfg = _minimal_config()
    assert build_text_enrichers(cfg) == []


def test_build_text_enrichers_skips_disabled():
    text_cfg = MagicMock()
    text_cfg.enabled = False
    cfg = _minimal_config(text_enrichers={"lrclib": text_cfg})
    assert build_text_enrichers(cfg) == []


def test_build_text_enrichers_skips_unknown(caplog):
    import logging

    text_cfg = MagicMock()
    text_cfg.enabled = True
    cfg = _minimal_config(text_enrichers={"nonexistent": text_cfg})
    with caplog.at_level(logging.WARNING, logger="mediainfo.wiring"):
        result = build_text_enrichers(cfg)
    assert result == []
    assert any("nonexistent" in r.message for r in caplog.records)


def test_build_text_enrichers_instantiates_enabled():
    text_cfg = MagicMock()
    text_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    cfg = _minimal_config(text_enrichers={"lrclib": text_cfg})

    with patch("mediainfo.registries.TEXT_ENRICHER_CLASSES", {"lrclib": fake_cls}):
        result = build_text_enrichers(cfg)

    args, _ = fake_cls.call_args
    assert args[0] is text_cfg
    assert isinstance(args[1], TextCache)
    assert result == [fake_cls.return_value]


def test_build_text_enrichers_shares_one_cache_across_plugins():
    lrclib_cfg = MagicMock()
    lrclib_cfg.enabled = True
    other_cfg = MagicMock()
    other_cfg.enabled = True
    fake_cls = MagicMock(side_effect=lambda cfg, cache: MagicMock(cache=cache))
    cfg = _minimal_config(text_enrichers={"lrclib": lrclib_cfg, "other": other_cfg})

    with patch(
        "mediainfo.registries.TEXT_ENRICHER_CLASSES", {"lrclib": fake_cls, "other": fake_cls}
    ):
        result = build_text_enrichers(cfg)

    assert result[0].cache is result[1].cache


def test_build_text_enrichers_passes_mediadata_store_to_mediadata_aware_enrichers():
    text_cfg = MagicMock()
    text_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    fake_store = MagicMock()
    cfg = _minimal_config(text_enrichers={"mediadata": text_cfg})

    with (
        patch("mediainfo.registries.TEXT_ENRICHER_CLASSES", {"mediadata": fake_cls}),
        patch("mediainfo.registries.MEDIADATA_AWARE_TEXT_ENRICHER_NAMES", {"mediadata"}),
    ):
        result = build_text_enrichers(cfg, mediadata_store=fake_store)

    fake_cls.assert_called_once_with(text_cfg, fake_store)
    assert result == [fake_cls.return_value]


def test_build_idle_source_returns_none_when_disabled():
    idle_cfg = MagicMock()
    idle_cfg.enabled = False
    cfg = _minimal_config(idle={"unsplash": idle_cfg})
    assert build_idle_source(cfg) is None


def test_build_idle_source_returns_instance_when_enabled():
    idle_cfg = MagicMock()
    idle_cfg.enabled = True

    fake_cls = MagicMock(return_value=MagicMock())
    cfg = _minimal_config(idle={"unsplash": idle_cfg})

    with patch("mediainfo.registries.IDLE_CLASSES", {"unsplash": fake_cls}):
        result = build_idle_source(cfg)

    fake_cls.assert_called_once_with(idle_cfg)
    assert result is fake_cls.return_value


def test_build_idle_source_returns_none_for_empty():
    cfg = _minimal_config()
    assert build_idle_source(cfg) is None


def test_build_idle_source_wraps_multiple_enabled_sources_in_composite():
    from mediainfo.idle.composite import CompositeIdleWallpaperSource

    unsplash_cfg = MagicMock()
    unsplash_cfg.enabled = True
    lastfm_cfg = MagicMock()
    lastfm_cfg.enabled = True

    fake_unsplash_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    fake_lastfm_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    cfg = _minimal_config(idle={"unsplash": unsplash_cfg, "lastfm": lastfm_cfg})

    with patch(
        "mediainfo.registries.IDLE_CLASSES",
        {"unsplash": fake_unsplash_cls, "lastfm": fake_lastfm_cls},
    ):
        result = build_idle_source(cfg)

    assert isinstance(result, CompositeIdleWallpaperSource)
    assert result.sources == [fake_unsplash_cls.return_value, fake_lastfm_cls.return_value]
    assert result.mode == "priority"


def test_build_idle_source_orders_by_idle_priority():
    from mediainfo.idle.composite import CompositeIdleWallpaperSource

    unsplash_cfg = MagicMock(enabled=True)
    lastfm_cfg = MagicMock(enabled=True)
    fake_unsplash_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    fake_lastfm_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    cfg = _minimal_config(
        idle={"unsplash": unsplash_cfg, "lastfm": lastfm_cfg},
        idle_priority=["lastfm", "unsplash"],
    )

    with patch(
        "mediainfo.registries.IDLE_CLASSES",
        {"unsplash": fake_unsplash_cls, "lastfm": fake_lastfm_cls},
    ):
        result = build_idle_source(cfg)

    assert isinstance(result, CompositeIdleWallpaperSource)
    assert result.sources == [fake_lastfm_cls.return_value, fake_unsplash_cls.return_value]


def test_build_idle_source_appends_unlisted_enabled_sources_after_priority_list():
    unsplash_cfg = MagicMock(enabled=True)
    lastfm_cfg = MagicMock(enabled=True)
    library_cfg = MagicMock(enabled=True)
    fake_unsplash_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    fake_lastfm_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    fake_library_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    cfg = _minimal_config(
        idle={"unsplash": unsplash_cfg, "lastfm": lastfm_cfg, "library": library_cfg},
        idle_priority=["lastfm"],  # unsplash/library not listed
    )

    with patch(
        "mediainfo.registries.IDLE_CLASSES",
        {"unsplash": fake_unsplash_cls, "lastfm": fake_lastfm_cls, "library": fake_library_cls},
    ):
        result = build_idle_source(cfg)

    assert result.sources == [
        fake_lastfm_cls.return_value, fake_unsplash_cls.return_value, fake_library_cls.return_value,
    ]


def test_build_idle_source_passes_through_idle_mode():
    unsplash_cfg = MagicMock(enabled=True)
    lastfm_cfg = MagicMock(enabled=True)
    fake_unsplash_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    fake_lastfm_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    cfg = _minimal_config(
        idle={"unsplash": unsplash_cfg, "lastfm": lastfm_cfg}, idle_mode="random",
    )

    with patch(
        "mediainfo.registries.IDLE_CLASSES",
        {"unsplash": fake_unsplash_cls, "lastfm": fake_lastfm_cls},
    ):
        result = build_idle_source(cfg)

    assert result.mode == "random"


def test_build_idle_source_passes_library_to_library_aware_classes():
    idle_cfg = MagicMock()
    idle_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    fake_library = MagicMock()
    cfg = _minimal_config(idle={"library": idle_cfg})

    with (
        patch("mediainfo.registries.IDLE_CLASSES", {"library": fake_cls}),
        patch("mediainfo.registries.LIBRARY_AWARE_IDLE_NAMES", {"library"}),
    ):
        result = build_idle_source(cfg, fake_library)

    fake_cls.assert_called_once_with(idle_cfg, fake_library)
    assert result is fake_cls.return_value


# ---------------------------------------------------------------------------
# start_orchestrator
# ---------------------------------------------------------------------------

def test_start_orchestrator_starts_and_returns_orchestrator():
    cfg = _minimal_config(
        priority=[],
        sources={},
        enrichers={},
        idle={},
        poll_interval_seconds=5,
        rotation_interval_seconds=30,
    )
    outputs = []
    cache = MagicMock()

    mock_orch = MagicMock()
    with patch("mediainfo.wiring.Orchestrator", return_value=mock_orch) as mock_cls:
        result = start_orchestrator(cfg, outputs, cache)

    mock_cls.assert_called_once()
    mock_orch.start.assert_called_once()
    assert result is mock_orch


# ---------------------------------------------------------------------------
# build_artwork_overrides / wire_artwork_overrides
# ---------------------------------------------------------------------------

def test_build_artwork_overrides_returns_none_when_disabled():
    cfg = MagicMock()
    cfg.overrides.enabled = False
    assert build_artwork_overrides(cfg) is None


def test_build_artwork_overrides_returns_store_when_enabled(tmp_path):
    from mediainfo.artwork_overrides import ArtworkOverrideStore

    cfg = MagicMock()
    cfg.overrides.enabled = True
    cfg.overrides.dir = str(tmp_path / "overrides")

    store = build_artwork_overrides(cfg)

    assert isinstance(store, ArtworkOverrideStore)
    assert store.dir == tmp_path / "overrides"


def test_wire_artwork_overrides_wires_config_ui_output_only():
    from mediainfo.outputs.config_ui import ConfigUiOutput

    config_output = MagicMock(spec=ConfigUiOutput)
    other_output = MagicMock()
    store = MagicMock()

    wire_artwork_overrides([config_output, other_output], store)

    config_output.set_artwork_overrides.assert_called_once_with(store)
    assert not other_output.set_artwork_overrides.called


def test_wire_artwork_overrides_passes_through_none():
    from mediainfo.outputs.config_ui import ConfigUiOutput

    config_output = MagicMock(spec=ConfigUiOutput)
    wire_artwork_overrides([config_output], None)
    config_output.set_artwork_overrides.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# wire_health_providers
# ---------------------------------------------------------------------------

def test_wire_health_providers_wires_web_config_ui_and_mqtt_outputs():
    from mediainfo.outputs.config_ui import ConfigUiOutput
    from mediainfo.outputs.mqtt import MqttOutput
    from mediainfo.outputs.web import WebOutput

    web_output = MagicMock(spec=WebOutput)
    config_output = MagicMock(spec=ConfigUiOutput)
    mqtt_output = MagicMock(spec=MqttOutput)
    other_output = MagicMock()

    orch = MagicMock()
    orch.get_health.return_value = {
        "active_source": None, "source_last_polled_ago": {}, "output_errors": {},
        "source_backoff_seconds": {}, "uptime_seconds": 0, "poll_interval_seconds": 5,
        "rotation_interval_seconds": 30, "now_playing": None, "idle_wallpapers_loaded": 0, "hitster_safe": False,
    }
    orch.sources = []
    orch.enrichers = []
    orch.idle_source = None

    cfg = MagicMock()
    cfg.sources = {}
    cfg.outputs = {}
    cfg.enrichers = {}
    cfg.idle = {}

    wire_health_providers([web_output, config_output, mqtt_output, other_output], orch, cfg)

    web_output.set_health_provider.assert_called_once()
    config_output.set_health_provider.assert_called_once()
    mqtt_output.set_health_provider.assert_called_once()
    assert not other_output.set_health_provider.called


# ---------------------------------------------------------------------------
# wire_hitster_safe
# ---------------------------------------------------------------------------

def test_wire_hitster_safe_wires_config_ui_and_mqtt_outputs_only():
    from mediainfo.outputs.config_ui import ConfigUiOutput
    from mediainfo.outputs.mqtt import MqttOutput
    from mediainfo.outputs.web import WebOutput

    web_output = MagicMock(spec=WebOutput)
    config_output = MagicMock(spec=ConfigUiOutput)
    mqtt_output = MagicMock(spec=MqttOutput)
    other_output = MagicMock()

    orch = MagicMock()
    orch.get_hitster_safe = MagicMock()
    orch.set_hitster_safe = MagicMock()

    wire_hitster_safe([web_output, config_output, mqtt_output, other_output], orch)

    config_output.set_hitster_safe_handlers.assert_called_once_with(
        orch.get_hitster_safe, orch.set_hitster_safe
    )
    mqtt_output.set_hitster_safe_handlers.assert_called_once_with(
        orch.get_hitster_safe, orch.set_hitster_safe
    )
    # WebOutput has no set_hitster_safe_handlers method at all (its spec mock
    # would raise AttributeError if code tried to call it) - confirming only
    # ConfigUiOutput/MqttOutput got wired.
    assert not other_output.set_hitster_safe_handlers.called


# ---------------------------------------------------------------------------
# wire_artwork_refresh
# ---------------------------------------------------------------------------

def test_wire_artwork_refresh_wires_mqtt_output_only():
    from mediainfo.outputs.config_ui import ConfigUiOutput
    from mediainfo.outputs.mqtt import MqttOutput

    config_output = MagicMock(spec=ConfigUiOutput)
    mqtt_output = MagicMock(spec=MqttOutput)
    other_output = MagicMock()

    orch = MagicMock()
    orch.request_artwork_refresh = MagicMock()

    wire_artwork_refresh([config_output, mqtt_output, other_output], orch)

    mqtt_output.set_refresh_artwork_handler.assert_called_once_with(orch.request_artwork_refresh)
    assert not other_output.set_refresh_artwork_handler.called


# ---------------------------------------------------------------------------
# wire_rotate_now
# ---------------------------------------------------------------------------

def test_wire_rotate_now_wires_mqtt_output_only():
    from mediainfo.outputs.config_ui import ConfigUiOutput
    from mediainfo.outputs.mqtt import MqttOutput

    config_output = MagicMock(spec=ConfigUiOutput)
    mqtt_output = MagicMock(spec=MqttOutput)
    other_output = MagicMock()

    orch = MagicMock()
    orch.request_rotation_now = MagicMock()

    wire_rotate_now([config_output, mqtt_output, other_output], orch)

    mqtt_output.set_rotate_now_handler.assert_called_once_with(orch.request_rotation_now)
    assert not other_output.set_rotate_now_handler.called
