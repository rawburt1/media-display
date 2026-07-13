"""Base class for artwork enricher plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Tuple

from mediainfo.models import NowPlaying


class ArtworkEnricher(ABC):
    """Adds extra Artwork entries to a NowPlaying's `images` list.

    Implementations must catch their own connection/network errors, log
    them, and leave `now_playing.images` unchanged on failure, so one
    unreachable enricher never breaks the polling loop.
    """

    # Registry key this enricher is known by (e.g. "musicbrainz") - None
    # (the default) means "not self-declared", i.e. look it up via
    # registries.enricher_name_for_class() as today.
    name: Optional[str] = None

    # Optional: the config dataclass (from mediainfo.config) that
    # configures this enricher, for a plugin that wants to declare the
    # pairing itself rather than relying on registries.py's
    # ENRICHER_CLASSES and mediainfo.config's ENRICHER_CONFIG_TYPES
    # staying in sync by registry key alone. None (the default) means
    # "not declared".
    config_class: Optional[type] = None

    # Optional free-form feature flags. wiring.build_enrichers() reads
    # "library"/"cache_dir"/"mediadata" off this to decide which extra
    # constructor argument (if any) to pass - see the relevant enricher
    # subclasses (e.g. FanartTvEnricher, AiArtworkEnricher,
    # MediaDataArtworkEnricher) for examples. Empty (the default) means no
    # extra argument.
    capabilities: frozenset = frozenset()

    @abstractmethod
    def enrich(self, now_playing: NowPlaying) -> None:
        """Mutate `now_playing.images` in place, appending any extra art."""

    def health_check(self) -> Optional[dict]:
        """Optional self-reported health detail. None (the default) means
        nothing extra to report."""
        return None

    def test_connection(self) -> Tuple[bool, str]:
        """Optional connectivity check for the config UI's "test
        connection" button. Default: not implemented here - today this is
        instead dispatched by name in
        mediainfo/configui/config_dashboard.py (test_enricher()); migrating
        an individual plugin's test logic to this method is a reasonable
        future increment, one plugin at a time, rather than all at once.
        """
        return False, "No connection test available for this plugin"
