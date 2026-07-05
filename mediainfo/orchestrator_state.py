"""Route-group state model: the per-group data the orchestrator's tick loop
tracks, and the pure functions that build/classify it.

Split out of orchestrator.py - these are the state containers and pure
(side-effect-free) helpers describing "what a route group is" and "what kind
of tick this is for it", kept separate from the polling/enrichment/routing
behavior that acts on them.
"""

from __future__ import annotations

import dataclasses
import enum
import re
from typing import Dict, List, Optional

from mediainfo.models import NowPlaying
from mediainfo.output_filter import ContentRules
from mediainfo.outputs.base import Output

# Matches one or more consecutive "(...)" groups trailing a song title,
# e.g. "(Live)", "(Remastered 2011) (Mono Mix)" - stripped from every
# source's title uniformly here, rather than per-source, so every output
# shows the same clean title regardless of which source produced it.
# Anchored to the end so a leading or mid-title "(...)" that's actually
# part of the song's real name (e.g. "(I Can't Get No) Satisfaction")
# is left alone.
_PARENTHETICAL_RE = re.compile(r"(?:\s*\([^)]*\))+\s*$")


def _strip_parenthetical(title: str) -> str:
    return re.sub(r"\s{2,}", " ", _PARENTHETICAL_RE.sub("", title)).strip()


@dataclasses.dataclass
class _RotationState:
    """An output's independent position in a randomized cycle through
    `NowPlaying.images`."""

    order: List[int]
    position: int
    last_rotation: float


@dataclasses.dataclass
class _RouteGroup:
    """One set of outputs sharing the same content-rule signature (see
    docs/per-output-routing.md) - they always agree on which item they'd
    show, so they share its state: the current item, each member output's
    rotation through that item's images, and the "nothing playing" grace
    clock.

    With no filters configured every output has the same (empty) rules and
    lands in one group, which reproduces the previous single-`_current`
    global-winner behavior exactly.
    """

    output_indices: List[int]
    # The group key: which items this group's outputs accept. active_hours
    # is deliberately not part of it (it gates display, not routing) - see
    # ContentRules and _recheck_filters.
    signature: ContentRules = ContentRules()
    current: Optional[NowPlaying] = None
    rotation_state: Dict[int, _RotationState] = dataclasses.field(default_factory=dict)
    # Member output indices currently blocked by their content filter
    # (allow/deny rules or active_hours). Filtered outputs do not receive
    # on_new_item() or update() calls while blocked.
    filtered_outputs: set = dataclasses.field(default_factory=set)
    # When this group's sources first reported "nothing playing" while
    # something was showing; None means either nothing is playing or the
    # source just resumed. See nothing_playing_grace_seconds.
    nothing_playing_since: Optional[float] = None


class _Transition(enum.Enum):
    """What kind of tick this is, decided purely from the current poll
    result and the orchestrator's existing state - before any enrichment,
    cache access, or output call happens. Keeping this decision free of
    side effects means it can be reasoned about (and tested) on its own,
    independently of mocking outputs/cache/enrichers.
    """

    NOTHING_PLAYING = enum.auto()
    SAME_ITEM_ROTATE = enum.auto()
    SAME_ITEM_NO_ARTWORK = enum.auto()
    NEW_ITEM = enum.auto()


def build_groups(outputs: List[Output]) -> List[_RouteGroup]:
    """Group outputs by their content-rule signature. Outputs are fixed for
    the life of the process (see __main__.py), so this is computed once.
    Always returns at least one group so the single-group aliases stay
    valid even with no outputs.
    """
    by_signature: Dict[ContentRules, _RouteGroup] = {}
    for index, output in enumerate(outputs):
        signature = ContentRules.from_config(getattr(output, "config", None))
        group = by_signature.get(signature)
        if group is None:
            group = _RouteGroup(output_indices=[], signature=signature)
            by_signature[signature] = group
        group.output_indices.append(index)
    return list(by_signature.values()) or [_RouteGroup(output_indices=[])]


def classify(group: _RouteGroup, now_playing: NowPlaying) -> _Transition:
    """Pure: decide what kind of tick this is for `group` from `now_playing`
    and `group.current` alone - no enrichment, no cache access, no output
    calls.
    """
    if group.current is not None and now_playing.identity == group.current.identity:
        return (
            _Transition.SAME_ITEM_ROTATE
            if group.current.images
            else _Transition.SAME_ITEM_NO_ARTWORK
        )
    return _Transition.NEW_ITEM
