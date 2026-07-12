"""AppServices: the cross-cutting capabilities an output plugin may need,
gathered into one object and handed to every output via Output.attach()
(see wiring.build_app_services()/attach_services()).

Before this, each capability (health reporting, playback history,
hitster-safe, artwork refresh/rotate-now, the shared MediaDataStore,
artwork overrides) had its own wire_*() function in wiring.py that
imported the concrete output classes it applied to and dispatched with
isinstance(). That meant every new cross-cutting capability added another
wire_*() function, another isinstance check, and another import - and
wiring.py (nominally "core") ended up knowing every output plugin's
concrete type. Here, wiring.py builds one AppServices and calls
output.attach(services) uniformly; each output pulls whatever fields it
cares about and ignores the rest, so adding a capability only means
adding a field here plus the one output that consumes it.

Every field is optional and independently meaningful when absent/None -
e.g. history=None means "the history feature is disabled" (see
HistoryConfig.enabled), not "not wired yet" - matching how the individual
setters this replaces already treated None before.
"""

from __future__ import annotations

import dataclasses
from typing import Callable, Optional

from mediainfo.artwork_overrides import ArtworkOverrideStore
from mediainfo.history import PlaybackHistory
from mediainfo.media_data_store import MediaDataStore


@dataclasses.dataclass
class AppServices:
    # Returns the /health JSON dict - see health.make_health_provider().
    health_provider: Optional[Callable[[], dict]] = None
    # Playback history store backing the /history page.
    history: Optional[PlaybackHistory] = None
    # Shared on-disk artwork/lyrics/metadata cache (see media_data_store.py).
    mediadata_store: Optional[MediaDataStore] = None
    # Manual per-title artwork pin store (see artwork_overrides.py).
    overrides: Optional[ArtworkOverrideStore] = None
    # Orchestrator.get_hitster_safe/set_hitster_safe - read/toggle
    # "Hitster-safe" mode (suppress music titles on every display).
    get_hitster_safe: Optional[Callable[[], bool]] = None
    set_hitster_safe: Optional[Callable[[bool], None]] = None
    # Orchestrator.request_artwork_refresh/request_rotation_now - ask the
    # next poll tick to re-enrich/re-push the current item, or immediately
    # advance every output's rotation.
    request_artwork_refresh: Optional[Callable[[], None]] = None
    request_rotation_now: Optional[Callable[[], None]] = None
