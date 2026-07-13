"""Tests for `python -m mediainfo set-password` (mediainfo.__main__._set_password_main)."""

import shutil
from pathlib import Path

import pytest

from mediainfo.__main__ import _set_password_main
from mediainfo.config import Config
from mediainfo.web_auth import verify_password

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    shutil.copy(EXAMPLE_CONFIG, path)
    return path


def test_sets_username_and_password_noninteractively(config_path):
    _set_password_main(
        [
            "--config",
            str(config_path),
            "--username",
            "admin",
            "--password",
            "hunter2",
        ]
    )

    cfg = Config.load(config_path)
    assert cfg.auth.username == "admin"
    assert cfg.auth.password != "hunter2"  # stored hashed, not plaintext
    assert verify_password("hunter2", cfg.auth.password)


def test_does_not_enable_auth_by_default(config_path):
    _set_password_main(
        [
            "--config",
            str(config_path),
            "--username",
            "admin",
            "--password",
            "hunter2",
        ]
    )

    cfg = Config.load(config_path)
    assert cfg.auth.enabled is False


def test_enable_flag_turns_auth_on(config_path):
    _set_password_main(
        [
            "--config",
            str(config_path),
            "--username",
            "admin",
            "--password",
            "hunter2",
            "--enable",
        ]
    )

    cfg = Config.load(config_path)
    assert cfg.auth.enabled is True


def test_reusing_existing_username_when_omitted(config_path):
    _set_password_main(
        [
            "--config",
            str(config_path),
            "--username",
            "admin",
            "--password",
            "first",
        ]
    )
    _set_password_main(
        [
            "--config",
            str(config_path),
            "--password",
            "second",
        ]
    )

    cfg = Config.load(config_path)
    assert cfg.auth.username == "admin"
    assert verify_password("second", cfg.auth.password)
    assert not verify_password("first", cfg.auth.password)


def test_preserves_comments_and_other_config(config_path):
    _set_password_main(
        [
            "--config",
            str(config_path),
            "--username",
            "admin",
            "--password",
            "hunter2",
        ]
    )

    text = config_path.read_text()
    assert "# Copy this file to config.yaml" in text

    cfg = Config.load(config_path)
    assert cfg.sources["kodi"].host == "192.168.1.21"  # untouched


def test_missing_config_file_exits_with_error(tmp_path, capsys):
    missing = tmp_path / "does-not-exist.yaml"

    with pytest.raises(SystemExit) as exc:
        _set_password_main(["--config", str(missing), "--username", "admin", "--password", "x"])

    assert exc.value.code == 1
    assert "not found" in capsys.readouterr().err


def test_prompts_when_password_omitted(config_path, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "prompted-secret")

    _set_password_main(["--config", str(config_path), "--username", "admin"])

    cfg = Config.load(config_path)
    assert verify_password("prompted-secret", cfg.auth.password)


def test_mismatched_confirmation_exits_without_saving(config_path, monkeypatch, capsys):
    original = Config.load(config_path).auth.password
    responses = iter(["one-value", "a-different-value"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(responses))

    with pytest.raises(SystemExit) as exc:
        _set_password_main(["--config", str(config_path), "--username", "admin"])

    assert exc.value.code == 1
    assert "did not match" in capsys.readouterr().err
    assert Config.load(config_path).auth.password == original


def test_prompts_for_username_when_none_configured_or_passed(tmp_path, monkeypatch):
    # config.example.yaml already has a placeholder auth.username, so start
    # from a config with none at all to exercise the "prompt" path.
    config_path = tmp_path / "config.yaml"
    config_path.write_text("poll_interval_seconds: 5\nauth:\n  enabled: false\n")
    monkeypatch.setattr("builtins.input", lambda prompt="": "prompted-user")

    _set_password_main(["--config", str(config_path), "--password", "hunter2"])

    cfg = Config.load(config_path)
    assert cfg.auth.username == "prompted-user"


def test_refuses_to_write_when_resulting_config_invalid(config_path, monkeypatch, capsys):
    original_text = config_path.read_text()

    def _boom(data):
        raise ValueError("simulated invalid config")

    monkeypatch.setattr("mediainfo.__main__.Config.from_dict", _boom)

    with pytest.raises(SystemExit) as exc:
        _set_password_main(["--config", str(config_path), "--username", "admin", "--password", "x"])

    assert exc.value.code == 1
    assert "invalid" in capsys.readouterr().err
    assert config_path.read_text() == original_text  # unchanged on failure


def test_prints_restart_required_note(config_path, capsys):
    _set_password_main(
        ["--config", str(config_path), "--username", "admin", "--password", "hunter2"]
    )

    out = capsys.readouterr().out
    assert "restart" in out.lower()
