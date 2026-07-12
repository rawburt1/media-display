"""Tests for _ArtworkPipeline's per-enricher enrichment deadline (C2 in
docs/architecture-usability-review-2026-07.md): a single hung/slow enricher
must not block the rest of enrich_item indefinitely, while normal
(fast-returning) enrichers keep running strictly in order - see
tests/test_orchestrator_routing.py for that ordering/sharing behavior,
unchanged by this feature.
"""

import threading
import time
from unittest.mock import MagicMock

from mediainfo.models import NowPlaying
from mediainfo.orchestrator import Orchestrator
from mediainfo.orchestrator_artwork import _ArtworkPipeline, _enricher_deadline


def _pipeline(enrichers=None, text_enrichers=None, enrichment_deadline_seconds=30):
    return _ArtworkPipeline(
        enrichers=enrichers or [],
        cache=MagicMock(),
        rotation_interval_seconds=30,
        call_output=MagicMock(),
        safe_call=Orchestrator._safe_call,
        text_enrichers=text_enrichers,
        enrichment_deadline_seconds=enrichment_deadline_seconds,
    )


class _SlowEnricher:
    """An enricher whose enrich() blocks far longer than any deadline used
    below, to prove the pipeline gives up waiting rather than blocking the
    tick on it."""

    def __init__(self, seconds=2.0, config=None):
        self.seconds = seconds
        self.config = config
        self.started = threading.Event()

    def enrich(self, now_playing):
        self.started.set()
        time.sleep(self.seconds)
        now_playing.title = "mutated-by-slow-enricher"


def test_enrich_item_moves_on_after_deadline_without_waiting_for_slow_enricher():
    slow = _SlowEnricher(seconds=2.0)
    fast = MagicMock()
    pipeline = _pipeline(enrichers=[slow, fast], enrichment_deadline_seconds=0.05)
    item = NowPlaying(source="kodi", media_type="movie", title="Original")

    start = time.monotonic()
    pipeline.enrich_item(item)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0  # gave up long before the slow enricher's 2s sleep
    assert slow.started.wait(timeout=1)  # sanity: it did actually start
    fast.enrich.assert_called_once_with(item)  # the tick still moved on to it
    assert item.title == "Original"  # abandoned enricher hadn't mutated it yet


def test_enrichment_deadline_uses_enrichers_own_timeout_seconds_config():
    class _Config:
        timeout_seconds = 0.05

    slow = _SlowEnricher(seconds=2.0, config=_Config())
    pipeline = _pipeline(enrichers=[slow], enrichment_deadline_seconds=10)
    item = NowPlaying(source="kodi", media_type="movie", title="Original")

    start = time.monotonic()
    pipeline.enrich_item(item)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0  # used the enricher's own 0.05s timeout, not the 10s default


def test_enricher_deadline_ignores_non_numeric_config_timeout():
    # MagicMock()-based enrichers (used throughout the orchestrator test
    # suite) auto-create a `.config.timeout_seconds` attribute that's just
    # another MagicMock - must not be mistaken for a real deadline.
    enricher = MagicMock()
    assert _enricher_deadline(enricher, default=12.0) == 12.0


def test_fast_enrichers_still_run_in_order():
    calls = []
    first = MagicMock(enrich=lambda item: calls.append("first"))
    second = MagicMock(enrich=lambda item: calls.append("second"))
    pipeline = _pipeline(enrichers=[first, second])
    item = NowPlaying(source="kodi", media_type="movie", title="Original")

    pipeline.enrich_item(item)

    assert calls == ["first", "second"]
