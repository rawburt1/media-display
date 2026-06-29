"""Tests for the central per-output content filter."""

from __future__ import annotations

import dataclasses
import datetime
from unittest.mock import patch

from mediainfo.models import NowPlaying
from mediainfo.output_filter import _in_active_hours, passes_filter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _Config:
    allow_media_types: list = dataclasses.field(default_factory=list)
    deny_media_types: list = dataclasses.field(default_factory=list)
    allow_sources: list = dataclasses.field(default_factory=list)
    deny_sources: list = dataclasses.field(default_factory=list)
    idle_when_filtered: bool = False
    active_hours: str = ""


def _np(source="sonos", media_type="music"):
    return NowPlaying(source=source, media_type=media_type, title="T", subtitle="S")


# ---------------------------------------------------------------------------
# passes_filter — no rules (backward-compatible default)
# ---------------------------------------------------------------------------


def test_no_rules_passes():
    assert passes_filter(_np(), _Config()) is True


def test_none_config_passes():
    assert passes_filter(_np(), None) is True


# ---------------------------------------------------------------------------
# deny_media_types
# ---------------------------------------------------------------------------


def test_deny_media_type_blocks():
    cfg = _Config(deny_media_types=["music"])
    assert passes_filter(_np(media_type="music"), cfg) is False


def test_deny_media_type_allows_other():
    cfg = _Config(deny_media_types=["music"])
    assert passes_filter(_np(media_type="movie"), cfg) is True


# ---------------------------------------------------------------------------
# deny_sources
# ---------------------------------------------------------------------------


def test_deny_source_blocks():
    cfg = _Config(deny_sources=["spotify"])
    assert passes_filter(_np(source="spotify"), cfg) is False


def test_deny_source_allows_other():
    cfg = _Config(deny_sources=["spotify"])
    assert passes_filter(_np(source="sonos"), cfg) is True


# ---------------------------------------------------------------------------
# allow_media_types
# ---------------------------------------------------------------------------


def test_allow_media_type_passes_listed():
    cfg = _Config(allow_media_types=["music", "episode"])
    assert passes_filter(_np(media_type="music"), cfg) is True


def test_allow_media_type_blocks_unlisted():
    cfg = _Config(allow_media_types=["music"])
    assert passes_filter(_np(media_type="movie"), cfg) is False


def test_empty_allow_media_types_passes_all():
    cfg = _Config(allow_media_types=[])
    assert passes_filter(_np(media_type="game"), cfg) is True


# ---------------------------------------------------------------------------
# allow_sources
# ---------------------------------------------------------------------------


def test_allow_source_passes_listed():
    cfg = _Config(allow_sources=["sonos", "spotify"])
    assert passes_filter(_np(source="sonos"), cfg) is True


def test_allow_source_blocks_unlisted():
    cfg = _Config(allow_sources=["sonos"])
    assert passes_filter(_np(source="kodi"), cfg) is False


# ---------------------------------------------------------------------------
# deny beats allow
# ---------------------------------------------------------------------------


def test_deny_beats_allow_on_media_type():
    cfg = _Config(allow_media_types=["music"], deny_media_types=["music"])
    assert passes_filter(_np(media_type="music"), cfg) is False


def test_deny_beats_allow_on_source():
    cfg = _Config(allow_sources=["sonos"], deny_sources=["sonos"])
    assert passes_filter(_np(source="sonos"), cfg) is False


# ---------------------------------------------------------------------------
# combined allow_media_types + allow_sources
# ---------------------------------------------------------------------------


def test_combined_both_must_pass():
    cfg = _Config(allow_media_types=["music"], allow_sources=["sonos"])
    assert passes_filter(_np(source="sonos", media_type="music"), cfg) is True
    assert passes_filter(_np(source="kodi", media_type="music"), cfg) is False
    assert passes_filter(_np(source="sonos", media_type="movie"), cfg) is False


# ---------------------------------------------------------------------------
# active_hours — non-wrapping window
# ---------------------------------------------------------------------------


def _fake_time(hh: int, mm: int):
    return patch(
        "mediainfo.output_filter.datetime.datetime",
        **{"now.return_value": datetime.datetime(2024, 1, 1, hh, mm, 30)},
    )


def test_active_hours_inside_window():
    with _fake_time(10, 0):
        assert _in_active_hours("08:00-22:00") is True


def test_active_hours_before_window():
    with _fake_time(7, 59):
        assert _in_active_hours("08:00-22:00") is False


def test_active_hours_after_window():
    with _fake_time(22, 1):
        assert _in_active_hours("08:00-22:00") is False


def test_active_hours_on_boundary_start():
    with _fake_time(8, 0):
        assert _in_active_hours("08:00-22:00") is True


def test_active_hours_on_boundary_end():
    with _fake_time(22, 0):
        assert _in_active_hours("08:00-22:00") is True


# ---------------------------------------------------------------------------
# active_hours — wrap-around window (e.g. 22:00-06:00)
# ---------------------------------------------------------------------------


def test_wrap_inside_after_start():
    with _fake_time(23, 0):
        assert _in_active_hours("22:00-06:00") is True


def test_wrap_inside_before_end():
    with _fake_time(3, 0):
        assert _in_active_hours("22:00-06:00") is True


def test_wrap_outside_midday():
    with _fake_time(12, 0):
        assert _in_active_hours("22:00-06:00") is False


def test_wrap_on_start_boundary():
    with _fake_time(22, 0):
        assert _in_active_hours("22:00-06:00") is True


def test_wrap_on_end_boundary():
    with _fake_time(6, 0):
        assert _in_active_hours("22:00-06:00") is True


# ---------------------------------------------------------------------------
# active_hours — malformed values are treated as always-active
# ---------------------------------------------------------------------------


def test_malformed_active_hours_passes():
    assert _in_active_hours("not-a-time") is True


def test_empty_active_hours_passes():
    cfg = _Config(active_hours="")
    assert passes_filter(_np(), cfg) is True


# ---------------------------------------------------------------------------
# active_hours integrated with passes_filter
# ---------------------------------------------------------------------------


def test_passes_filter_blocks_outside_active_hours():
    cfg = _Config(active_hours="08:00-22:00")
    with _fake_time(3, 0):
        assert passes_filter(_np(), cfg) is False


def test_passes_filter_passes_inside_active_hours():
    cfg = _Config(active_hours="08:00-22:00")
    with _fake_time(12, 0):
        assert passes_filter(_np(), cfg) is True
