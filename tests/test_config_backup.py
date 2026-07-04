"""Tests for mediainfo.config_backup.backup_config_file."""

import time

from mediainfo.config_backup import backup_config_file


def test_returns_none_when_config_does_not_exist_yet(tmp_path):
    config_path = tmp_path / "config.yaml"

    assert backup_config_file(config_path) is None
    assert not (tmp_path / ".config_backups").exists()


def test_copies_existing_config_into_backup_dir(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("poll_interval_seconds: 5\n")

    backup_path = backup_config_file(config_path)

    assert backup_path is not None
    assert backup_path.parent == tmp_path / ".config_backups"
    assert backup_path.read_text() == "poll_interval_seconds: 5\n"
    # Original is untouched by taking a backup.
    assert config_path.read_text() == "poll_interval_seconds: 5\n"


def test_each_call_backs_up_the_current_contents(tmp_path):
    config_path = tmp_path / "config.yaml"

    config_path.write_text("poll_interval_seconds: 5\n")
    backup_config_file(config_path)

    config_path.write_text("poll_interval_seconds: 10\n")
    second_backup = backup_config_file(config_path)

    assert second_backup.read_text() == "poll_interval_seconds: 10\n"
    backups = list((tmp_path / ".config_backups").glob("config.yaml.*.bak"))
    assert len(backups) == 2


def test_prunes_backups_beyond_keep_limit(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("poll_interval_seconds: 5\n")

    times = iter(range(1000, 1030))
    monkeypatch.setattr(time, "strftime", lambda fmt: str(next(times)))

    for _ in range(5):
        backup_config_file(config_path, keep=3)

    backups = sorted((tmp_path / ".config_backups").glob("config.yaml.*.bak"))
    assert len(backups) == 3


def test_disambiguates_backups_taken_within_the_same_second(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("poll_interval_seconds: 5\n")

    monkeypatch.setattr(time, "strftime", lambda fmt: "20260101T000000")

    first = backup_config_file(config_path)
    config_path.write_text("poll_interval_seconds: 10\n")
    second = backup_config_file(config_path)

    assert first != second
    assert first.exists() and second.exists()
    assert second.read_text() == "poll_interval_seconds: 10\n"
