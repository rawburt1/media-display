"""Tests for mediainfo.disk_eviction: size-capped LRU eviction (M2)."""

from __future__ import annotations

from pathlib import Path

from mediainfo.disk_eviction import EvictionUnit, evict_by_size, units_to_evict


def _unit(name: str, last_used: float, size_bytes: int) -> EvictionUnit:
    return EvictionUnit(path=Path(f"/fake/{name}"), last_used=last_used, size_bytes=size_bytes)


def test_nothing_evicted_when_under_the_cap():
    units = [_unit("a", 1, 100), _unit("b", 2, 100)]
    assert units_to_evict(units, max_total_bytes=1000) == []


def test_nothing_evicted_when_exactly_at_the_cap():
    units = [_unit("a", 1, 500), _unit("b", 2, 500)]
    assert units_to_evict(units, max_total_bytes=1000) == []


def test_evicts_the_least_recently_used_first():
    old = _unit("old", last_used=1, size_bytes=100)
    mid = _unit("mid", last_used=2, size_bytes=100)
    new = _unit("new", last_used=3, size_bytes=100)
    # Total is 300; cap is 250 - evicting just `old` (200 remaining) is
    # already enough, so `mid`/`new` both survive.
    result = units_to_evict([new, old, mid], max_total_bytes=250)
    assert result == [old]


def test_evicts_multiple_units_until_under_the_cap():
    old = _unit("old", last_used=1, size_bytes=100)
    mid = _unit("mid", last_used=2, size_bytes=100)
    new = _unit("new", last_used=3, size_bytes=100)
    result = units_to_evict([new, old, mid], max_total_bytes=100)
    assert result == [old, mid]


def test_evicts_everything_if_the_cap_is_smaller_than_a_single_unit():
    units = [_unit("only", last_used=1, size_bytes=500)]
    assert units_to_evict(units, max_total_bytes=100) == units


def test_ties_broken_deterministically_by_path():
    a = _unit("a", last_used=1, size_bytes=100)
    b = _unit("b", last_used=1, size_bytes=100)
    result = units_to_evict([b, a], max_total_bytes=100)
    assert result == [a]


def test_empty_units_evicts_nothing():
    assert units_to_evict([], max_total_bytes=0) == []


def test_evict_by_size_deletes_via_the_given_callback_in_order():
    old = _unit("old", last_used=1, size_bytes=100)
    new = _unit("new", last_used=2, size_bytes=100)
    deleted: list = []

    result = evict_by_size([new, old], max_total_bytes=100, delete=deleted.append)

    assert result == [old.path]
    assert deleted == [old.path]


def test_evict_by_size_deletes_nothing_when_under_the_cap():
    old = _unit("old", last_used=1, size_bytes=100)
    deleted: list = []

    result = evict_by_size([old], max_total_bytes=1000, delete=deleted.append)

    assert result == []
    assert deleted == []
