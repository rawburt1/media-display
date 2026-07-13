"""Tests for MediaSource.test_connection()'s generic implementation
(mediainfo/sources/base.py) - shared by every source that doesn't need
its own override (see tests/test_appletv.py for the one that does)."""

import logging
from typing import Optional

from mediainfo.models import NowPlaying
from mediainfo.sources.base import MediaSource


class _FakeSource(MediaSource):
    def __init__(self, result: Optional[NowPlaying] = None, poll_failed: bool = False):
        self._result = result
        self.last_poll_failed = poll_failed

    def get_now_playing(self) -> Optional[NowPlaying]:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def test_connected_with_now_playing():
    result = NowPlaying(source="fake", media_type="music", title="Bohemian Rhapsody")
    ok, message = _FakeSource(result=result).test_connection()
    assert ok is True
    assert "Bohemian Rhapsody" in message


def test_connected_with_nothing_playing():
    ok, message = _FakeSource(result=None).test_connection()
    assert ok is True
    assert "nothing currently playing" in message


def test_reports_last_poll_failed():
    ok, message = _FakeSource(result=None, poll_failed=True).test_connection()
    assert ok is False
    assert "connect" in message.lower()


def test_exception_is_caught():
    ok, message = _FakeSource(result=RuntimeError("boom")).test_connection()
    assert ok is False
    assert "boom" in message


# ---------------------------------------------------------------------------
# log_poll_error / note_poll_recovered (M8 - first-failure ERROR, then
# DEBUG until recovery, so an offline device doesn't spam an
# ERROR-with-traceback on every backoff retry)
# ---------------------------------------------------------------------------


def _try_something(source: MediaSource, log: logging.Logger) -> None:
    try:
        raise RuntimeError("device unreachable")
    except RuntimeError:
        source.log_poll_error(log, "fake source error")


def test_first_failure_logs_at_error(caplog):
    source = _FakeSource()
    with caplog.at_level(logging.DEBUG):
        _try_something(source, logging.getLogger("test.fake_source"))
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.ERROR
    assert caplog.records[0].exc_info is not None  # traceback still attached


def test_repeated_failures_downgrade_to_debug(caplog):
    source = _FakeSource()
    log = logging.getLogger("test.fake_source")
    with caplog.at_level(logging.DEBUG):
        _try_something(source, log)
        _try_something(source, log)
        _try_something(source, log)
    levels = [r.levelno for r in caplog.records]
    assert levels == [logging.ERROR, logging.DEBUG, logging.DEBUG]
    # DEBUG repeats still carry the traceback - not just quieter, still
    # useful for troubleshooting with DEBUG logging turned on.
    assert all(r.exc_info is not None for r in caplog.records)


def test_note_poll_recovered_resets_the_streak_so_a_fresh_outage_is_error_again(caplog):
    source = _FakeSource()
    log = logging.getLogger("test.fake_source")
    with caplog.at_level(logging.DEBUG):
        _try_something(source, log)  # ERROR
        _try_something(source, log)  # DEBUG
        source.note_poll_recovered()
        _try_something(source, log)  # a fresh outage - ERROR again
    levels = [r.levelno for r in caplog.records]
    assert levels == [logging.ERROR, logging.DEBUG, logging.ERROR]


def test_note_poll_recovered_before_any_failure_is_a_harmless_no_op():
    _FakeSource().note_poll_recovered()  # must not raise
