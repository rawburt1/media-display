"""Tests for `python -m mediainfo restore-backup` (mediainfo.__main__._restore_backup_main)."""

import shutil
from pathlib import Path

import pytest

from mediainfo.__main__ import _restore_backup_main
from mediainfo.config import Config
from mediainfo.config_backup import backup_config_file

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    shutil.copy(EXAMPLE_CONFIG, path)
    return path


def test_errors_when_no_backups_exist(config_path, capsys):
    with pytest.raises(SystemExit) as exc:
        _restore_backup_main(["--config", str(config_path)])

    assert exc.value.code == 1
    assert "no backups found" in capsys.readouterr().err.lower()


def test_list_prints_backup_names_without_restoring(config_path, capsys):
    backup_config_file(config_path)
    original_text = config_path.read_text()

    _restore_backup_main(["--config", str(config_path), "--list"])

    out = capsys.readouterr().out
    assert config_path.name in out
    assert config_path.read_text() == original_text


def test_restores_latest_backup_noninteractively(config_path):
    original_text = config_path.read_text()
    backup_config_file(config_path)
    config_path.write_text("poll_interval_seconds: 999\n")

    _restore_backup_main(["--config", str(config_path), "--backup", "latest", "--yes"])

    assert config_path.read_text() == original_text


def test_restore_backs_up_current_contents_first(config_path):
    backup_config_file(config_path)
    config_path.write_text("poll_interval_seconds: 999\n")

    _restore_backup_main(["--config", str(config_path), "--backup", "latest", "--yes"])

    backup_dir = config_path.parent / ".config_backups"
    contents = [b.read_text() for b in backup_dir.glob("*.bak")]
    assert "poll_interval_seconds: 999\n" in contents


def test_restore_by_exact_backup_name(config_path):
    original_text = config_path.read_text()
    backup_path = backup_config_file(config_path)
    config_path.write_text("poll_interval_seconds: 999\n")

    _restore_backup_main(["--config", str(config_path), "--backup", backup_path.name, "--yes"])

    assert config_path.read_text() == original_text


def test_unknown_backup_name_errors(config_path, capsys):
    backup_config_file(config_path)

    with pytest.raises(SystemExit) as exc:
        _restore_backup_main(
            ["--config", str(config_path), "--backup", "does-not-exist.bak", "--yes"]
        )

    assert exc.value.code == 1
    assert "no backup named" in capsys.readouterr().err.lower()


def test_prompts_for_selection_when_backup_omitted(config_path, monkeypatch):
    original_text = config_path.read_text()
    backup_config_file(config_path)
    config_path.write_text("poll_interval_seconds: 999\n")

    monkeypatch.setattr("builtins.input", lambda prompt="": "1")

    _restore_backup_main(["--config", str(config_path), "--yes"])

    assert config_path.read_text() == original_text


def test_declining_confirmation_leaves_config_untouched(config_path, monkeypatch):
    backup_config_file(config_path)
    config_path.write_text("poll_interval_seconds: 999\n")

    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    _restore_backup_main(["--config", str(config_path), "--backup", "latest"])

    assert config_path.read_text() == "poll_interval_seconds: 999\n"


def test_warns_when_restored_config_is_invalid(config_path, capsys):
    backup_config_file(config_path)  # backup of the valid example config
    config_path.write_text("not: [valid, config, at, all")  # broken YAML on top

    # Overwrite the backup file itself with unparseable YAML to simulate
    # restoring something that no longer loads.
    backup_dir = config_path.parent / ".config_backups"
    backup_file = next(backup_dir.glob("*.bak"))
    backup_file.write_text("not: [valid, yaml, at, all")

    _restore_backup_main(["--config", str(config_path), "--backup", "latest", "--yes"])

    assert "fails to load" in capsys.readouterr().err.lower()


def test_restored_config_loads_successfully(config_path):
    original_username = Config.load(config_path).auth.username
    backup_config_file(config_path)
    config_path.write_text("poll_interval_seconds: 999\n")

    _restore_backup_main(["--config", str(config_path), "--backup", "latest", "--yes"])

    assert Config.load(config_path).auth.username == original_username
