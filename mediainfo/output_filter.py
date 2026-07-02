"""Central per-output content filter.

Filter evaluation order (first failing rule wins):

1. deny_media_types  — exact deny on media_type
2. deny_sources      — exact deny on source
3. allow_media_types — if non-empty, media_type must appear in the list
4. allow_sources     — if non-empty, source must appear in the list
5. active_hours      — if set, current local time must fall inside the window

Missing or empty rules pass unconditionally (backward-compatible default).
deny always beats allow: a type/source in both deny and allow is denied.
active_hours wraps around midnight ("22:00-06:00" means 22:00–23:59 or 00:00–06:00).
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any


@dataclasses.dataclass(frozen=True)
class ContentRules:
    """The routing-relevant subset of an output's filter config - the
    allow/deny rules, without active_hours (that gates *whether* an output
    displays, not *what* it would show; see docs/per-output-routing.md).

    Frozen/hashable so outputs sharing the same rules can be grouped into
    one route group by using their ContentRules as the group key.
    """

    allow_media_types: tuple = ()
    deny_media_types: tuple = ()
    allow_sources: tuple = ()
    deny_sources: tuple = ()

    @classmethod
    def from_config(cls, config: Any) -> "ContentRules":
        # Guard: only apply rules when the config field is the expected
        # Python type. Non-list values (e.g. from a MagicMock in tests)
        # are treated as "no rule".
        def norm(name: str) -> tuple:
            value = getattr(config, name, None)
            return tuple(sorted(value)) if isinstance(value, list) else ()

        return cls(
            allow_media_types=norm("allow_media_types"),
            deny_media_types=norm("deny_media_types"),
            allow_sources=norm("allow_sources"),
            deny_sources=norm("deny_sources"),
        )

    def accepts(self, now_playing: Any) -> bool:
        """First failing rule wins; deny always beats allow (see module
        docstring). Empty rules pass unconditionally."""
        if now_playing.media_type in self.deny_media_types:
            return False
        if now_playing.source in self.deny_sources:
            return False
        if self.allow_media_types and now_playing.media_type not in self.allow_media_types:
            return False
        if self.allow_sources and now_playing.source not in self.allow_sources:
            return False
        return True


def passes_filter(now_playing: Any, config: Any) -> bool:
    """Return True if *now_playing* passes all filters defined in *config*."""
    if config is None:
        return True

    if not ContentRules.from_config(config).accepts(now_playing):
        return False

    active_hours = getattr(config, "active_hours", None)
    if isinstance(active_hours, str) and active_hours and not _in_active_hours(active_hours):
        return False
    return True


def _in_active_hours(active_hours: str) -> bool:
    """Return True if the current local time falls within *active_hours*.

    Format: "HH:MM-HH:MM".  Wrap-around windows (e.g. "22:00-06:00") are
    supported and mean "active if now >= start OR now <= end".
    Malformed values are treated as always-active to avoid blocking outputs.
    """
    try:
        start_str, end_str = active_hours.split("-", 1)
        start = _parse_hhmm(start_str)
        end = _parse_hhmm(end_str)
    except (ValueError, AttributeError):
        return True

    now = datetime.datetime.now().time().replace(second=0, microsecond=0)

    if start <= end:
        return start <= now <= end
    # wrap-around (e.g. 22:00-06:00)
    return now >= start or now <= end


def _parse_hhmm(s: str) -> datetime.time:
    h, m = s.strip().split(":")
    return datetime.time(int(h), int(m))


def validate_active_hours(value: str) -> str | None:
    """Return None if *value* is a valid active_hours string, or an error message."""
    if not value:
        return None
    try:
        start_str, end_str = value.split("-", 1)
        _parse_hhmm(start_str)
        _parse_hhmm(end_str)
        return None
    except (ValueError, AttributeError):
        return f"invalid format {value!r} — expected HH:MM-HH:MM (e.g. '08:00-22:00')"
