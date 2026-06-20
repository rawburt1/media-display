"""Tests for main entry-point utilities: signal handling and config hot-reload."""

from __future__ import annotations

import signal
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

import logging

from mediainfo.__main__ import (
    _file_mtime,
    _make_stop_handler,
    _shutdown_outputs,
    _warn_output_changes,
    _validate_config,
    _build_sources,
    _build_enrichers,
    _build_idle_source,
    _start_orchestrator,
    _setup_logging,
)
from mediainfo.config import LoggingConfig


# ---------------------------------------------------------------------------
# _file_mtime
# ---------------------------------------------------------------------------

def test_file_mtime_returns_none_for_missing_file(tmp_path):
    assert _file_mtime(tmp_path / "missing.yaml") is None


def test_file_mtime_returns_positive_float(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("poll_interval_seconds: 5\n")
    assert _file_mtime(p) > 0


def test_file_mtime_changes_after_write(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("a: 1\n")
    mtime1 = _file_mtime(p)
    time.sleep(0.01)
    p.write_text("a: 2\n")
    p.touch()  # ensure mtime update even on fast filesystems
    mtime2 = _file_mtime(p)
    assert mtime2 >= mtime1


# ---------------------------------------------------------------------------
# _make_stop_handler
# ---------------------------------------------------------------------------

def test_make_stop_handler_sets_event():
    ev = threading.Event()
    handler = _make_stop_handler(ev)
    handler(signal.SIGTERM, None)
    assert ev.is_set()


def test_make_stop_handler_works_with_sigint():
    ev = threading.Event()
    handler = _make_stop_handler(ev)
    handler(signal.SIGINT, None)
    assert ev.is_set()


def test_make_stop_handler_idempotent():
    ev = threading.Event()
    handler = _make_stop_handler(ev)
    handler(signal.SIGTERM, None)
    handler(signal.SIGTERM, None)  # second call must not raise
    assert ev.is_set()


def test_make_stop_handler_independent_events():
    ev1 = threading.Event()
    ev2 = threading.Event()
    h1 = _make_stop_handler(ev1)
    h2 = _make_stop_handler(ev2)
    h1(signal.SIGTERM, None)
    assert ev1.is_set()
    assert not ev2.is_set()


# ---------------------------------------------------------------------------
# _shutdown_outputs
# ---------------------------------------------------------------------------

def test_shutdown_outputs_calls_on_idle_on_all():
    outputs = [MagicMock(), MagicMock(), MagicMock()]
    _shutdown_outputs(outputs)
    for out in outputs:
        out.on_idle.assert_called_once_with()


def test_shutdown_outputs_continues_despite_one_failure():
    bad = MagicMock()
    bad.on_idle.side_effect = RuntimeError("device unreachable")
    good = MagicMock()
    _shutdown_outputs([bad, good])  # must not raise
    good.on_idle.assert_called_once_with()


def test_shutdown_outputs_empty_list():
    _shutdown_outputs([])  # no-op, must not raise


# ---------------------------------------------------------------------------
# _warn_output_changes
# ---------------------------------------------------------------------------

def test_warn_output_changes_warns_when_outputs_differ(caplog):
    import logging

    # Use real distinct objects so != is True
    old = MagicMock()
    old.outputs = {"web": [object()]}
    new = MagicMock()
    new.outputs = {"web": [object()]}  # different instance

    with caplog.at_level(logging.WARNING, logger="mediainfo.__main__"):
        _warn_output_changes(old, new)

    assert any("restart" in r.message.lower() for r in caplog.records)


def test_warn_output_changes_silent_when_same(caplog):
    import logging

    cfg = MagicMock()
    cfg.outputs = {}

    with caplog.at_level(logging.WARNING, logger="mediainfo.__main__"):
        _warn_output_changes(cfg, cfg)  # same object → equal

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == []


# ---------------------------------------------------------------------------
# _validate_config
# ---------------------------------------------------------------------------

def test_validate_config_warns_when_enabled_source_missing_from_priority(caplog):
    cfg = MagicMock()
    cfg.priority = ["kodi"]
    kodi_cfg = MagicMock(enabled=True)
    youtube_cfg = MagicMock(enabled=True)
    cfg.sources = {"kodi": kodi_cfg, "youtube": youtube_cfg}

    with caplog.at_level(logging.WARNING, logger="mediainfo.__main__"):
        _validate_config(cfg)

    assert any("youtube" in r.message and "priority" in r.message for r in caplog.records)
    assert not any("kodi" in r.message for r in caplog.records)


def test_validate_config_silent_when_disabled_source_missing_from_priority(caplog):
    cfg = MagicMock()
    cfg.priority = []
    cfg.sources = {"youtube": MagicMock(enabled=False)}

    with caplog.at_level(logging.WARNING, logger="mediainfo.__main__"):
        _validate_config(cfg)

    assert caplog.records == []


def test_validate_config_silent_when_all_enabled_sources_listed(caplog):
    cfg = MagicMock()
    cfg.priority = ["kodi", "youtube"]
    cfg.sources = {"kodi": MagicMock(enabled=True), "youtube": MagicMock(enabled=True)}

    with caplog.at_level(logging.WARNING, logger="mediainfo.__main__"):
        _validate_config(cfg)

    assert caplog.records == []


def _config_for_credential_test(**overrides):
    """A MagicMock Config with empty sources/enrichers/idle/auth by
    default, so only the field(s) set via `overrides` (e.g.
    enrichers={"thetvdb": ...}) are exercised - everything else falls
    through the "not in dict" early-continue, unlike a bare MagicMock()
    whose auto-vivified attributes would all look "present".
    """
    cfg = MagicMock()
    cfg.priority = []
    cfg.sources = overrides.get("sources", {})
    cfg.enrichers = overrides.get("enrichers", {})
    cfg.idle = overrides.get("idle", {})
    cfg.auth = overrides.get("auth", MagicMock(enabled=False))
    return cfg


def test_validate_config_warns_when_required_credential_is_blank(caplog):
    from mediainfo.config import TheTvDbConfig

    cfg = _config_for_credential_test(
        enrichers={"thetvdb": TheTvDbConfig(enabled=True, api_key="")}
    )

    with caplog.at_level(logging.WARNING, logger="mediainfo.__main__"):
        _validate_config(cfg)

    assert any("thetvdb" in r.message and "api_key" in r.message for r in caplog.records)


def test_validate_config_warns_with_multiple_missing_fields(caplog):
    from mediainfo.config import SpotifyConfig

    cfg = _config_for_credential_test(
        sources={"spotify": SpotifyConfig(enabled=True, client_id="", client_secret="")}
    )

    with caplog.at_level(logging.WARNING, logger="mediainfo.__main__"):
        _validate_config(cfg)

    assert any(
        "client_id" in r.message and "client_secret" in r.message for r in caplog.records
    )


def test_validate_config_silent_when_credential_is_set(caplog):
    from mediainfo.config import TheTvDbConfig

    cfg = _config_for_credential_test(
        enrichers={"thetvdb": TheTvDbConfig(enabled=True, api_key="real-key")}
    )

    with caplog.at_level(logging.WARNING, logger="mediainfo.__main__"):
        _validate_config(cfg)

    assert caplog.records == []


def test_validate_config_silent_when_credential_consumer_disabled(caplog):
    from mediainfo.config import TheTvDbConfig

    cfg = _config_for_credential_test(
        enrichers={"thetvdb": TheTvDbConfig(enabled=False, api_key="")}
    )

    with caplog.at_level(logging.WARNING, logger="mediainfo.__main__"):
        _validate_config(cfg)

    assert caplog.records == []


def test_validate_config_does_not_warn_about_appletv_credentials():
    # Blank appletv credentials are a normal pre-pairing state, not a
    # mistake - this dict simply has no entry for it (see comment above
    # _REQUIRED_CREDENTIAL_FIELDS), so it's never flagged.
    from mediainfo.__main__ import _REQUIRED_CREDENTIAL_FIELDS
    assert ("sources", "appletv") not in _REQUIRED_CREDENTIAL_FIELDS


def test_validate_config_warns_when_auth_enabled_with_blank_credentials(caplog):
    from mediainfo.config import AuthConfig

    cfg = _config_for_credential_test(auth=AuthConfig(enabled=True, username="", password=""))

    with caplog.at_level(logging.WARNING, logger="mediainfo.__main__"):
        _validate_config(cfg)

    assert any("auth" in r.message.lower() for r in caplog.records)


def test_validate_config_silent_when_auth_enabled_with_credentials(caplog):
    from mediainfo.config import AuthConfig

    cfg = _config_for_credential_test(
        auth=AuthConfig(enabled=True, username="admin", password="secret")
    )

    with caplog.at_level(logging.WARNING, logger="mediainfo.__main__"):
        _validate_config(cfg)

    assert caplog.records == []


def test_validate_config_silent_when_auth_disabled_with_blank_credentials(caplog):
    from mediainfo.config import AuthConfig

    cfg = _config_for_credential_test(auth=AuthConfig(enabled=False, username="", password=""))

    with caplog.at_level(logging.WARNING, logger="mediainfo.__main__"):
        _validate_config(cfg)

    assert caplog.records == []


# ---------------------------------------------------------------------------
# _build_sources / _build_enrichers / _build_idle_source
# ---------------------------------------------------------------------------

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


def test_build_sources_empty_priority():
    cfg = _minimal_config()
    assert _build_sources(cfg) == []


def test_build_sources_skips_disabled():
    source_cfg = MagicMock()
    source_cfg.enabled = False
    cfg = _minimal_config(priority=["kodi"], sources={"kodi": source_cfg})
    assert _build_sources(cfg) == []


def test_build_sources_skips_unknown(caplog):
    import logging

    source_cfg = MagicMock()
    source_cfg.enabled = True
    cfg = _minimal_config(priority=["nonexistent"], sources={"nonexistent": source_cfg})
    with caplog.at_level(logging.WARNING, logger="mediainfo.__main__"):
        result = _build_sources(cfg)
    assert result == []
    assert any("nonexistent" in r.message for r in caplog.records)


def test_build_sources_instantiates_enabled():
    source_cfg = MagicMock()
    source_cfg.enabled = True

    fake_cls = MagicMock(return_value=MagicMock())
    cfg = _minimal_config(priority=["kodi"], sources={"kodi": source_cfg})

    with patch("mediainfo.__main__.SOURCE_CLASSES", {"kodi": fake_cls}):
        result = _build_sources(cfg)

    fake_cls.assert_called_once_with(source_cfg)
    assert result == [fake_cls.return_value]


def test_build_enrichers_skips_disabled():
    enc_cfg = MagicMock()
    enc_cfg.enabled = False
    cfg = _minimal_config(enrichers={"fanarttv": enc_cfg})
    assert _build_enrichers(cfg) == []


def test_build_enrichers_instantiates_enabled():
    enc_cfg = MagicMock()
    enc_cfg.enabled = True

    fake_cls = MagicMock(return_value=MagicMock())
    cfg = _minimal_config(enrichers={"fanarttv": enc_cfg})

    with patch("mediainfo.__main__.ENRICHER_CLASSES", {"fanarttv": fake_cls}):
        result = _build_enrichers(cfg)

    fake_cls.assert_called_once_with(enc_cfg)
    assert result == [fake_cls.return_value]


def test_build_enrichers_passes_library_to_library_aware_enrichers():
    enc_cfg = MagicMock()
    enc_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    fake_library = MagicMock()
    cfg = _minimal_config(enrichers={"fanarttv": enc_cfg})

    with (
        patch("mediainfo.__main__.ENRICHER_CLASSES", {"fanarttv": fake_cls}),
        patch("mediainfo.__main__._LIBRARY_AWARE_ENRICHERS", {fake_cls}),
    ):
        result = _build_enrichers(cfg, fake_library)

    fake_cls.assert_called_once_with(enc_cfg, fake_library)
    assert result == [fake_cls.return_value]


def test_build_idle_source_returns_none_when_disabled():
    idle_cfg = MagicMock()
    idle_cfg.enabled = False
    cfg = _minimal_config(idle={"unsplash": idle_cfg})
    assert _build_idle_source(cfg) is None


def test_build_idle_source_returns_instance_when_enabled():
    idle_cfg = MagicMock()
    idle_cfg.enabled = True

    fake_cls = MagicMock(return_value=MagicMock())
    cfg = _minimal_config(idle={"unsplash": idle_cfg})

    with patch("mediainfo.__main__.IDLE_CLASSES", {"unsplash": fake_cls}):
        result = _build_idle_source(cfg)

    fake_cls.assert_called_once_with(idle_cfg)
    assert result is fake_cls.return_value


def test_build_idle_source_returns_none_for_empty():
    cfg = _minimal_config()
    assert _build_idle_source(cfg) is None


def test_build_idle_source_passes_library_to_library_aware_classes():
    idle_cfg = MagicMock()
    idle_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    fake_library = MagicMock()
    cfg = _minimal_config(idle={"library": idle_cfg})

    with (
        patch("mediainfo.__main__.IDLE_CLASSES", {"library": fake_cls}),
        patch("mediainfo.__main__._LIBRARY_AWARE_IDLE_CLASSES", {fake_cls}),
    ):
        result = _build_idle_source(cfg, fake_library)

    fake_cls.assert_called_once_with(idle_cfg, fake_library)
    assert result is fake_cls.return_value


# ---------------------------------------------------------------------------
# _start_orchestrator
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
    with patch("mediainfo.__main__.Orchestrator", return_value=mock_orch) as mock_cls:
        result = _start_orchestrator(cfg, outputs, cache)

    mock_cls.assert_called_once()
    mock_orch.start.assert_called_once()
    assert result is mock_orch


# ---------------------------------------------------------------------------
# _setup_logging
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_root_logger():
    root = logging.getLogger()
    original_level = root.level
    original_handlers = list(root.handlers)
    yield
    root.setLevel(original_level)
    root.handlers = original_handlers


def test_setup_logging_defaults_to_info():
    _setup_logging(LoggingConfig())
    assert logging.getLogger().level == logging.INFO


def test_setup_logging_honors_debug_level():
    _setup_logging(LoggingConfig(level="DEBUG"))
    assert logging.getLogger().level == logging.DEBUG


def test_setup_logging_is_case_insensitive():
    _setup_logging(LoggingConfig(level="warning"))
    assert logging.getLogger().level == logging.WARNING


def test_setup_logging_falls_back_to_info_for_invalid_level():
    _setup_logging(LoggingConfig(level="NOT_A_LEVEL"))
    assert logging.getLogger().level == logging.INFO


# ---------------------------------------------------------------------------
# _wire_health_providers
# ---------------------------------------------------------------------------

def test_wire_health_providers_wires_web_and_config_ui_outputs():
    from mediainfo.__main__ import _wire_health_providers
    from mediainfo.outputs.config_ui import ConfigUiOutput
    from mediainfo.outputs.web import WebOutput

    web_output = MagicMock(spec=WebOutput)
    config_output = MagicMock(spec=ConfigUiOutput)
    other_output = MagicMock()

    orch = MagicMock()
    orch.get_health.return_value = {
        "active_source": None, "source_last_polled_ago": {}, "output_errors": {},
        "source_backoff_seconds": {}, "uptime_seconds": 0, "poll_interval_seconds": 5,
        "rotation_interval_seconds": 30, "now_playing": None, "idle_wallpapers_loaded": 0,
    }
    orch.sources = []
    orch.enrichers = []
    orch.idle_source = None

    cfg = MagicMock()
    cfg.sources = {}
    cfg.outputs = {}
    cfg.enrichers = {}
    cfg.idle = {}

    _wire_health_providers([web_output, config_output, other_output], orch, cfg)

    web_output.set_health_provider.assert_called_once()
    config_output.set_health_provider.assert_called_once()
    assert not other_output.set_health_provider.called


# ---------------------------------------------------------------------------
# _config_detail_fields
# ---------------------------------------------------------------------------

def test_config_detail_fields_excludes_secrets_and_enabled():
    from mediainfo.__main__ import _config_detail_fields
    from mediainfo.config import KodiConfig

    cfg = KodiConfig(enabled=True, host="192.168.1.21", port=8080, username="kodi", password="kodi")
    detail = _config_detail_fields(cfg)

    assert detail == {"host": "192.168.1.21", "port": 8080, "username": "kodi"}


def test_config_detail_fields_omits_empty_values():
    from mediainfo.__main__ import _config_detail_fields
    from mediainfo.config import KodiConfig

    cfg = KodiConfig(enabled=True, host="", port=8080)
    detail = _config_detail_fields(cfg)

    assert "host" not in detail
    assert detail["port"] == 8080


def test_config_detail_fields_returns_empty_for_none():
    from mediainfo.__main__ import _config_detail_fields

    assert _config_detail_fields(None) == {}


# ---------------------------------------------------------------------------
# _make_health_provider - source error messaging + config detail on cards
# ---------------------------------------------------------------------------

def test_health_provider_includes_config_fields_and_error_message_for_backed_off_source():
    from mediainfo.__main__ import _make_health_provider
    from mediainfo.config import KodiConfig

    source = MagicMock()
    source.name = "kodi"

    orch = MagicMock()
    orch.sources = [source]
    orch.enrichers = []
    orch.idle_source = None
    orch.get_health.return_value = {
        "active_source": None,
        "source_last_polled_ago": {"kodi": 1.0},
        "output_errors": {},
        "source_backoff_seconds": {"kodi": 30.0},
        "uptime_seconds": 0,
        "poll_interval_seconds": 5,
        "rotation_interval_seconds": 30,
        "now_playing": None,
        "idle_wallpapers_loaded": 0,
    }

    cfg = MagicMock()
    cfg.sources = {"kodi": KodiConfig(enabled=True, host="192.168.1.21", port=8080)}
    cfg.outputs = {}
    cfg.enrichers = {}
    cfg.idle = {}

    health = _make_health_provider(orch, cfg, [])()
    kodi_entry = next(s for s in health["sources"] if s["name"] == "kodi")

    assert kodi_entry["status"] == "error"
    assert kodi_entry["host"] == "192.168.1.21"
    assert kodi_entry["port"] == 8080
    assert "retrying in 30.0s" in kodi_entry["last_error"]
