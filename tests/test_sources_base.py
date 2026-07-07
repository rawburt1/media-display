"""Tests for MediaSource.test_connection()'s generic implementation
(mediainfo/sources/base.py) - shared by every source that doesn't need
its own override (see tests/test_appletv.py for the one that does)."""

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
