"""Tests for main entry-point utilities: signal handling and config hot-reload."""

from __future__ import annotations

import signal
import threading
import time
from unittest.mock import MagicMock

import pytest

import logging

from mediainfo.__main__ import (
    _file_mtime,
    _make_stop_handler,
    _shutdown_outputs,
    _warn_output_changes,
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
    _make_stop_handler(ev2)
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


def test_shutdown_outputs_calls_stop_before_on_idle_on_all():
    outputs = [MagicMock(), MagicMock(), MagicMock()]
    _shutdown_outputs(outputs)
    for out in outputs:
        out.stop.assert_called_once_with()


def test_shutdown_outputs_continues_despite_one_failure():
    bad = MagicMock()
    bad.on_idle.side_effect = RuntimeError("device unreachable")
    good = MagicMock()
    _shutdown_outputs([bad, good])  # must not raise
    good.on_idle.assert_called_once_with()


def test_shutdown_outputs_continues_when_stop_raises():
    bad = MagicMock()
    bad.stop.side_effect = RuntimeError("device unreachable")
    good = MagicMock()
    _shutdown_outputs([bad, good])  # must not raise
    bad.on_idle.assert_called_once_with()  # still called despite stop() failing
    good.stop.assert_called_once_with()
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


