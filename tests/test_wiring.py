"""Tests for mediainfo.wiring: building sources/enrichers/idle sources/
outputs from config, and wiring cross-cutting state onto outputs.
"""

from unittest.mock import MagicMock, patch

from mediainfo.wiring import (
    build_enrichers,
    build_idle_source,
    build_sources,
    start_orchestrator,
    wire_health_providers,
    wire_hitster_safe,
)


def _minimal_config(**kwargs):
    """Return a MagicMock that quacks like a Config."""
    cfg = MagicMock()
    cfg.priority = []
    cfg.sources = {}
    cfg.enrichers = {}
    cfg.idle = {}
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


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

    with patch("mediainfo.registries.ENRICHER_CLASSES", {"fanarttv": fake_cls}):
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
        patch("mediainfo.registries.LIBRARY_AWARE_ENRICHERS", {fake_cls}),
    ):
        result = build_enrichers(cfg, fake_library)

    fake_cls.assert_called_once_with(enc_cfg, fake_library)
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


def test_build_idle_source_merges_multiple_enabled_sources():
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


def test_build_idle_source_passes_library_to_library_aware_classes():
    idle_cfg = MagicMock()
    idle_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    fake_library = MagicMock()
    cfg = _minimal_config(idle={"library": idle_cfg})

    with (
        patch("mediainfo.registries.IDLE_CLASSES", {"library": fake_cls}),
        patch("mediainfo.registries.LIBRARY_AWARE_IDLE_CLASSES", {fake_cls}),
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
# wire_health_providers
# ---------------------------------------------------------------------------

def test_wire_health_providers_wires_web_and_config_ui_outputs():
    from mediainfo.outputs.config_ui import ConfigUiOutput
    from mediainfo.outputs.web import WebOutput

    web_output = MagicMock(spec=WebOutput)
    config_output = MagicMock(spec=ConfigUiOutput)
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

    wire_health_providers([web_output, config_output, other_output], orch, cfg)

    web_output.set_health_provider.assert_called_once()
    config_output.set_health_provider.assert_called_once()
    assert not other_output.set_health_provider.called


# ---------------------------------------------------------------------------
# wire_hitster_safe
# ---------------------------------------------------------------------------

def test_wire_hitster_safe_wires_config_ui_output_only():
    from mediainfo.outputs.config_ui import ConfigUiOutput
    from mediainfo.outputs.web import WebOutput

    web_output = MagicMock(spec=WebOutput)
    config_output = MagicMock(spec=ConfigUiOutput)
    other_output = MagicMock()

    orch = MagicMock()
    orch.get_hitster_safe = MagicMock()
    orch.set_hitster_safe = MagicMock()

    wire_hitster_safe([web_output, config_output, other_output], orch)

    config_output.set_hitster_safe_handlers.assert_called_once_with(
        orch.get_hitster_safe, orch.set_hitster_safe
    )
    # WebOutput has no set_hitster_safe_handlers method at all (its spec mock
    # would raise AttributeError if code tried to call it) - confirming only
    # ConfigUiOutput got wired.
    assert not other_output.set_hitster_safe_handlers.called
