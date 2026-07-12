"""Tests for mediainfo.config.migrations.migrate_config."""

import logging

from mediainfo.config import migrations
from mediainfo.config.migrations import CURRENT_CONFIG_VERSION, migrate_config


def test_missing_config_version_is_treated_as_current_and_left_untouched():
    raw = {"poll_interval_seconds": 9}
    result = migrate_config(raw)
    assert result is raw
    assert "config_version" not in result


def test_explicit_current_version_is_left_untouched():
    raw = {"config_version": CURRENT_CONFIG_VERSION, "poll_interval_seconds": 9}
    result = migrate_config(raw)
    assert result is raw


def test_non_integer_config_version_is_treated_as_1_with_warning(caplog):
    raw = {"config_version": "not-a-number"}
    with caplog.at_level(logging.WARNING, logger="mediainfo.config.migrations"):
        result = migrate_config(raw)
    assert result is raw
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


def test_from_dict_applies_migrations_before_building_config(monkeypatch):
    from mediainfo.config import Config

    def _rename(data):
        data["poll_interval_seconds"] = data.pop("old_poll_interval_seconds")
        return data

    monkeypatch.setattr(migrations, "CURRENT_CONFIG_VERSION", 2)
    monkeypatch.setattr(migrations, "_MIGRATIONS", {1: _rename})

    config = Config.from_dict({"config_version": 1, "old_poll_interval_seconds": 42})
    assert config.poll_interval_seconds == 42
