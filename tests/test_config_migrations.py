"""Tests for mediainfo.config.migrations.migrate_config."""

import logging

from mediainfo.config import migrations
from mediainfo.config.migrations import CURRENT_CONFIG_VERSION, migrate_config


def test_missing_config_version_is_treated_as_1_and_migrated_forward():
    raw = {"poll_interval_seconds": 9}
    result = migrate_config(raw)
    assert result["poll_interval_seconds"] == 9
    assert result["config_version"] == CURRENT_CONFIG_VERSION


def test_explicit_current_version_is_left_untouched():
    raw = {"config_version": CURRENT_CONFIG_VERSION, "poll_interval_seconds": 9}
    result = migrate_config(raw)
    assert result is raw


def test_non_integer_config_version_is_treated_as_1_with_warning(caplog):
    raw = {"config_version": "not-a-number"}
    with caplog.at_level(logging.WARNING, logger="mediainfo.config.migrations"):
        result = migrate_config(raw)
    assert result["config_version"] == CURRENT_CONFIG_VERSION
    assert any("config_version" in r.message for r in caplog.records)


def test_future_version_is_left_untouched_with_warning(caplog):
    raw = {"config_version": CURRENT_CONFIG_VERSION + 1, "poll_interval_seconds": 9}
    with caplog.at_level(logging.WARNING, logger="mediainfo.config.migrations"):
        result = migrate_config(raw)
    assert result is raw
    assert result["poll_interval_seconds"] == 9
    assert any("newer than this build" in r.message for r in caplog.records)


def test_registered_migration_is_applied_and_version_bumped(monkeypatch):
    def _rename_old_key(data):
        data["new_key"] = data.pop("old_key")
        return data

    monkeypatch.setattr(migrations, "CURRENT_CONFIG_VERSION", 2)
    monkeypatch.setattr(migrations, "_MIGRATIONS", {1: _rename_old_key})

    raw = {"config_version": 1, "old_key": "value"}
    result = migrate_config(raw)

    assert result is not raw
    assert result["new_key"] == "value"
    assert "old_key" not in result
    assert result["config_version"] == 2


def test_multiple_registered_migrations_are_applied_in_order(monkeypatch):
    def _v1_to_v2(data):
        data["v2_key"] = data.pop("v1_key")
        return data

    def _v2_to_v3(data):
        data["v3_key"] = data.pop("v2_key")
        return data

    monkeypatch.setattr(migrations, "CURRENT_CONFIG_VERSION", 3)
    monkeypatch.setattr(migrations, "_MIGRATIONS", {1: _v1_to_v2, 2: _v2_to_v3})

    raw = {"config_version": 1, "v1_key": "value"}
    result = migrate_config(raw)

    assert result["v3_key"] == "value"
    assert result["config_version"] == 3


def test_missing_migration_stops_the_walk_partway(monkeypatch):
    # If a gap exists between the declared version and CURRENT_CONFIG_VERSION
    # (e.g. a migration was never written for some version), stop rather
    # than skip ahead silently - leaves the dict at whatever version the
    # last successful migration reached.
    def _v1_to_v2(data):
        data["v2_key"] = data.pop("v1_key")
        return data

    monkeypatch.setattr(migrations, "CURRENT_CONFIG_VERSION", 3)
    monkeypatch.setattr(migrations, "_MIGRATIONS", {1: _v1_to_v2})

    raw = {"config_version": 1, "v1_key": "value"}
    result = migrate_config(raw)

    assert result["v2_key"] == "value"
    assert result["config_version"] == 2


# ---------------------------------------------------------------------------
# v1 -> v2: per-output host/port dropped in favor of config.http
# ---------------------------------------------------------------------------


def test_v1_to_v2_drops_host_and_port_from_single_instance_output():
    raw = {
        "config_version": 1,
        "outputs": {"web": {"enabled": True, "host": "0.0.0.0", "port": 8090}},
    }
    result = migrate_config(raw)
    assert result["outputs"]["web"] == {"enabled": True}
    assert result["config_version"] == CURRENT_CONFIG_VERSION


def test_v1_to_v2_drops_host_and_port_from_every_instance_in_a_list():
    raw = {
        "config_version": 1,
        "outputs": {
            "config": [
                {"enabled": True, "host": "0.0.0.0", "port": 8094},
                {"enabled": True, "host": "0.0.0.0", "port": 8095, "label": "dashboard"},
            ]
        },
    }
    result = migrate_config(raw)
    assert result["outputs"]["config"] == [
        {"enabled": True},
        {"enabled": True, "label": "dashboard"},
    ]


def test_v1_to_v2_keeps_nest_hub_server_host_but_drops_server_port():
    raw = {
        "config_version": 1,
        "outputs": {
            "nest_hub": {"enabled": True, "server_host": "192.168.1.40", "server_port": 8092}
        },
    }
    result = migrate_config(raw)
    assert result["outputs"]["nest_hub"] == {"enabled": True, "server_host": "192.168.1.40"}


def test_v1_to_v2_warns_when_config_host_is_not_the_default(caplog):
    raw = {"config_version": 1, "outputs": {"config": {"enabled": True, "host": "127.0.0.1"}}}
    with caplog.at_level(logging.WARNING, logger="mediainfo.config.migrations"):
        migrate_config(raw)
    assert any("outputs.config.host" in r.message for r in caplog.records)


def test_v1_to_v2_no_warning_when_config_host_is_the_default(caplog):
    raw = {"config_version": 1, "outputs": {"config": {"enabled": True, "host": "0.0.0.0"}}}
    with caplog.at_level(logging.WARNING, logger="mediainfo.config.migrations"):
        migrate_config(raw)
    assert not any("outputs.config.host" in r.message for r in caplog.records)


def test_v1_to_v2_no_warning_when_config_host_is_absent(caplog):
    raw = {"config_version": 1, "outputs": {"config": {"enabled": True}}}
    with caplog.at_level(logging.WARNING, logger="mediainfo.config.migrations"):
        migrate_config(raw)
    assert not any("outputs.config.host" in r.message for r in caplog.records)


def test_v1_to_v2_tolerates_missing_or_non_dict_outputs():
    assert migrate_config({"config_version": 1})["config_version"] == CURRENT_CONFIG_VERSION
    assert migrate_config({"config_version": 1, "outputs": []})["outputs"] == []


def test_v1_to_v2_leaves_unrelated_output_types_untouched():
    raw = {"config_version": 1, "outputs": {"pixoo": {"enabled": True, "device_ip": "1.2.3.4"}}}
    result = migrate_config(raw)
    assert result["outputs"]["pixoo"] == {"enabled": True, "device_ip": "1.2.3.4"}


def test_from_dict_applies_migrations_before_building_config(monkeypatch):
    from mediainfo.config import Config

    def _rename(data):
        data["poll_interval_seconds"] = data.pop("old_poll_interval_seconds")
        return data

    monkeypatch.setattr(migrations, "CURRENT_CONFIG_VERSION", 2)
    monkeypatch.setattr(migrations, "_MIGRATIONS", {1: _rename})

    config = Config.from_dict({"config_version": 1, "old_poll_interval_seconds": 42})
    assert config.poll_interval_seconds == 42
