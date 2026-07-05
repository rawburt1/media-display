"""Base class for text enricher plugins - lyrics, AI-generated mood/
description/trivia text, and similar, as opposed to ArtworkEnricher (see
enrichers/base.py), which adds images.

Foundation for roadmap items 8 (lyrics) and 9 (AI-generated text) - no
concrete implementation lives here yet; this establishes the interface,
plugin contract, and orchestrator wiring so those can be added later as
plain plugin files + one registry entry each, with no further changes to
the orchestrator/wiring/config plumbing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Tuple

from mediainfo.models import NowPlaying


class TextEnricher(ABC):
    """Adds lyrics/description-style text to a NowPlaying, in place - e.g.
    NowPlaying.lyrics/synced_lyrics or an entry in NowPlaying.ai_text.

    Implementations must catch their own connection/network errors, log
    them, and leave NowPlaying's text fields unchanged on failure, so one
    unreachable enricher never breaks the polling loop - same contract as
    ArtworkEnricher.
    """

    # Registry key this enricher is known by (e.g. "lrclib") - None (the
    # default) means "not self-declared".
    name: Optional[str] = None

    # The config dataclass (from mediainfo.config) that configures this
    # enricher, if it wants to declare the pairing itself. None (the
    # default) means "not declared".
    config_class: Optional[type] = None

    # Optional free-form feature flags - not consumed anywhere yet; a hook
    # for future capability queries without another base-class change.
    capabilities: frozenset = frozenset()

    @abstractmethod
    def enrich(self, now_playing: NowPlaying) -> None:
        """Mutate now_playing's text fields in place, appending/setting
        whatever this enricher looks up."""

    def health_check(self) -> Optional[dict]:
        """Optional self-reported health detail. None (the default) means
        nothing extra to report."""
        return None

    def test_connection(self) -> Tuple[bool, str]:
        """Optional connectivity check for the config UI's "test
        connection" button. Default: not implemented."""
        return False, "No connection test available for this plugin"
