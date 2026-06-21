"""Tests for mediainfo.health: building the /health JSON payload."""

from unittest.mock import MagicMock

from mediainfo.health import config_detail_fields, make_health_provider


# ---------------------------------------------------------------------------
# config_detail_fields
# ---------------------------------------------------------------------------

def test_config_detail_fields_excludes_secrets_and_enabled():
    from mediainfo.config import KodiConfig

    cfg = KodiConfig(enabled=True, host="192.168.1.21", port=8080, username="kodi", password="kodi")
    detail = config_detail_fields(cfg)

    assert detail == {"host": "192.168.1.21", "port": 8080, "username": "kodi"}


def test_config_detail_fields_omits_empty_values():
    from mediainfo.config import KodiConfig

    cfg = KodiConfig(enabled=True, host="", port=8080)
    detail = config_detail_fields(cfg)

    assert "host" not in detail
    assert detail["port"] == 8080


def test_config_detail_fields_returns_empty_for_none():
    assert config_detail_fields(None) == {}


# ---------------------------------------------------------------------------
# make_health_provider - source error messaging + config detail on cards
# ---------------------------------------------------------------------------

def test_health_provider_includes_config_fields_and_error_message_for_backed_off_source():
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
        "idle_wallpapers_loaded": 0, "hitster_safe": False,
    }

    cfg = MagicMock()
    cfg.sources = {"kodi": KodiConfig(enabled=True, host="192.168.1.21", port=8080)}
    cfg.outputs = {}
    cfg.enrichers = {}
    cfg.idle = {}

    health = make_health_provider(orch, cfg, [])()
    kodi_entry = next(s for s in health["sources"] if s["name"] == "kodi")

    assert kodi_entry["status"] == "error"
    assert kodi_entry["host"] == "192.168.1.21"
    assert kodi_entry["port"] == 8080
    assert "retrying in 30.0s" in kodi_entry["last_error"]


def test_health_provider_assigns_per_type_instance_index_to_outputs():
    from mediainfo.config import UlanziConfig
    from mediainfo.outputs.ulanzi import UlanziOutput

    output1 = UlanziOutput(UlanziConfig(enabled=True, device_ip="1.1.1.1"))
    output2 = UlanziOutput(UlanziConfig(enabled=True, device_ip="2.2.2.2"))

    orch = MagicMock()
    orch.sources = []
    orch.enrichers = []
    orch.idle_source = None
    orch.get_health.return_value = {
        "active_source": None, "source_last_polled_ago": {}, "output_errors": {},
        "source_backoff_seconds": {}, "uptime_seconds": 0, "poll_interval_seconds": 5,
        "rotation_interval_seconds": 30, "now_playing": None, "idle_wallpapers_loaded": 0, "hitster_safe": False,
    }

    cfg = MagicMock()
    cfg.sources = {}
    cfg.outputs = {}
    cfg.enrichers = {}
    cfg.idle = {}

    health = make_health_provider(orch, cfg, [output1, output2])()
    ulanzi_entries = [o for o in health["outputs"] if o["type"] == "ulanzi"]

    assert len(ulanzi_entries) == 2
    assert {e["instance_index"] for e in ulanzi_entries} == {0, 1}
    by_index = {e["instance_index"]: e for e in ulanzi_entries}
    assert by_index[0]["device_ip"] == "1.1.1.1"
    assert by_index[1]["device_ip"] == "2.2.2.2"


# ---------------------------------------------------------------------------
# _registered_but_inactive / _inactive_outputs / _inactive_idle_sources
# ---------------------------------------------------------------------------

def test_registered_but_inactive_disabled_when_configured():
    from mediainfo.config import KodiConfig
    from mediainfo.health import _registered_but_inactive

    entries = _registered_but_inactive(
        active_names=set(),
        registry={"kodi": object()},
        config_section={"kodi": KodiConfig(enabled=False, host="192.168.1.21")},
    )

    assert entries == [
        {"name": "kodi", "status": "disabled", "host": "192.168.1.21", "port": 8080}
    ]


def test_registered_but_inactive_not_configured_when_no_config_section():
    from mediainfo.health import _registered_but_inactive

    entries = _registered_but_inactive(
        active_names=set(), registry={"kodi": object()}, config_section={}
    )

    assert entries == [{"name": "kodi", "status": "not_configured"}]


def test_registered_but_inactive_skips_active_names():
    from mediainfo.health import _registered_but_inactive

    entries = _registered_but_inactive(
        active_names={"kodi"}, registry={"kodi": object()}, config_section={}
    )

    assert entries == []


def test_inactive_outputs_disabled_when_config_list_present():
    from mediainfo.health import _inactive_outputs

    entries = _inactive_outputs(
        active_types=set(), registry={"web": object()}, config_outputs={"web": [object()]}
    )

    assert entries == [{"type": "web", "status": "disabled", "instance_index": 0}]


def test_inactive_outputs_not_configured_when_config_list_empty():
    from mediainfo.health import _inactive_outputs

    entries = _inactive_outputs(
        active_types=set(), registry={"web": object()}, config_outputs={"web": []}
    )

    assert entries == [{"type": "web", "status": "not_configured", "instance_index": 0}]


def test_inactive_idle_sources_status_matches_enabled_flag():
    from mediainfo.health import _inactive_idle_sources

    enabled = MagicMock(enabled=True)
    disabled = MagicMock(enabled=False)
    entries = _inactive_idle_sources(
        active_names=set(),
        registry={"unsplash": object(), "lastfm": object()},
        config_idle={"unsplash": enabled, "lastfm": disabled},
    )

    by_type = {e["type"]: e["status"] for e in entries}
    assert by_type["unsplash"] == "ok"
    assert by_type["lastfm"] == "disabled"


def test_inactive_idle_sources_not_configured_when_missing():
    from mediainfo.health import _inactive_idle_sources

    entries = _inactive_idle_sources(
        active_names=set(), registry={"unsplash": object()}, config_idle={}
    )

    assert all(e["status"] == "not_configured" for e in entries)
