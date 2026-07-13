"""Size-capped LRU eviction (M2 in
docs/architecture-usability-review-2026-07.md): "music/ cache tier is
never purged by design and mediadata/ grows per artist/album forever -
unbounded disk growth on small devices (a Pi) is the likeliest way this
app dies after two years."

Both mediainfo.cache.ImageCache's music tier and mediainfo.media_data_store
.MediaDataStore keep content that's deliberately *not* purged by age (a
frequently-replayed album shouldn't be re-fetched every 30 days the way a
movie poster is) - but "never purged by age" still needs a backstop once
total size grows past what the disk can hold, hence a size cap with LRU
eviction (oldest-last-used goes first) rather than the age-based purge
those two already have for their other tiers.

Deliberately a tiny, dependency-free function: callers own the "what
counts as a unit and how do I delete one" specifics (a single file for
ImageCache's flat hash-named layout; a whole per-item directory for
MediaDataStore's nested movies/series/music tree) - this only owns the
"which units, in what order, until the total is back under the cap"
decision, so both callers share one tested implementation of that.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Callable, List, Sequence


@dataclasses.dataclass(frozen=True)
class EvictionUnit:
    """One deletable thing under LRU-by-size eviction - a single cached
    file (ImageCache) or a whole item directory (MediaDataStore)."""

    path: Path
    last_used: float  # epoch seconds - larger is more recently used
    size_bytes: int


def units_to_evict(units: Sequence[EvictionUnit], max_total_bytes: int) -> List[EvictionUnit]:
    """Return the least-recently-used units to delete so the remaining
    total is <= max_total_bytes.

    Ties in last_used are broken by path (for deterministic tests/logs) -
    doesn't matter functionally, since a real tie means "used at the same
    moment", not a meaningful ordering.
    """
    total = sum(u.size_bytes for u in units)
    if total <= max_total_bytes:
        return []

    ordered = sorted(units, key=lambda u: (u.last_used, str(u.path)))
    to_evict: List[EvictionUnit] = []
    for unit in ordered:
        if total <= max_total_bytes:
            break
        to_evict.append(unit)
        total -= unit.size_bytes
    return to_evict


def evict_by_size(
    units: Sequence[EvictionUnit],
    max_total_bytes: int,
    delete: Callable[[Path], None],
) -> List[Path]:
    """units_to_evict() + actually delete them via *delete* (a callable so
    callers can use shutil.rmtree for a directory unit or Path.unlink for
    a file unit). Returns the paths actually deleted, in eviction order.
    A single unit's delete() failing (e.g. already gone, permissions) is
    the caller's problem - this doesn't swallow exceptions, matching every
    other eviction/purge path in this codebase (see
    mediainfo.cache.ImageCache.purge_expired, which lets its own caller's
    _safe_call wrapper handle failures instead of catching them here).
    """
    to_evict = units_to_evict(units, max_total_bytes)
    deleted = []
    for unit in to_evict:
        delete(unit.path)
        deleted.append(unit.path)
    return deleted
