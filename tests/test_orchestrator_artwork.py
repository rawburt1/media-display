"""Tests for _ArtworkPipeline's per-enricher enrichment deadline and artwork
prefetching (C2 in docs/architecture-usability-review-2026-07.md): a single
hung/slow enricher must not block the rest of enrich_item indefinitely,
while normal (fast-returning) enrichers keep running strictly in order -
see tests/test_orchestrator_routing.py for that ordering/sharing behavior,
unchanged by this feature. Separately, enrich_item() also prefetches every
enriched image into the cache concurrently, so per-output artwork fetches
in show_image_for_output() find it already cached.
"""

import threading
import time
from unittest.mock import MagicMock

from mediainfo.models import Artwork, NowPlaying
from mediainfo.orchestrator import Orchestrator
from mediainfo.orchestrator_artwork import _ArtworkPipeline, _enricher_deadline


def _pipeline(
    enrichers=None,
    text_enrichers=None,
    enrichment_deadline_seconds=30,
    artwork_prefetch_deadline_seconds=30,
    cache=None,
):
    return _ArtworkPipeline(
        enrichers=enrichers or [],
        cache=cache if cache is not None else MagicMock(),
        rotation_interval_seconds=30,
        call_output=MagicMock(),
        safe_call=Orchestrator._safe_call,
        text_enrichers=text_enrichers,
        enrichment_deadline_seconds=enrichment_deadline_seconds,
        artwork_prefetch_deadline_seconds=artwork_prefetch_deadline_seconds,
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


class _RecordingCache:
    """A fake ImageCache.get_path that records which artwork/tier it was
    called with and can be told to block one specific URL, to prove
    prefetch_images() fetches every image concurrently rather than one at
    a time."""

    def __init__(self, slow_url=None, slow_seconds=2.0, raise_for_url=None):
        self.calls = []
        self.slow_url = slow_url
        self.slow_seconds = slow_seconds
        self.raise_for_url = raise_for_url
        self.slow_started = threading.Event()

    def get_path(self, artwork, tier="default"):
        self.calls.append((artwork.url, tier))
        if artwork.url == self.raise_for_url:
            raise RuntimeError("simulated download failure")
        if artwork.url == self.slow_url:
            self.slow_started.set()
            time.sleep(self.slow_seconds)
        return f"/cache/{artwork.url}"


def test_prefetch_images_fetches_every_enriched_image():
    cache = _RecordingCache()
    pipeline = _pipeline(cache=cache)
    item = NowPlaying(source="kodi", media_type="movie", title="Original")
    item.images = [Artwork(url="https://example/a.jpg"), Artwork(url="https://example/b.jpg")]

    pipeline.enrich_item(item)

    assert sorted(cache.calls) == [
        ("https://example/a.jpg", "default"),
        ("https://example/b.jpg", "default"),
    ]


def test_prefetch_images_uses_music_tier_for_music_items():
    cache = _RecordingCache()
    pipeline = _pipeline(cache=cache)
    item = NowPlaying(source="spotify", media_type="music", title="Original")
    item.images = [Artwork(url="https://example/cover.jpg")]

    pipeline.enrich_item(item)

    assert cache.calls == [("https://example/cover.jpg", "music")]


def test_prefetch_images_does_nothing_for_an_item_with_no_images():
    cache = MagicMock()
    pipeline = _pipeline(cache=cache)
    item = NowPlaying(source="kodi", media_type="movie", title="Original")

    pipeline.enrich_item(item)

    cache.get_path.assert_not_called()


def test_prefetch_images_fetches_concurrently_not_one_at_a_time():
    # One artwork's download blocks far longer than the whole test's
    # timeout budget; if fetches ran serially, the second URL's call
    # would never happen in time.
    cache = _RecordingCache(slow_url="https://example/slow.jpg", slow_seconds=5.0)
    pipeline = _pipeline(cache=cache, artwork_prefetch_deadline_seconds=0.2)
    item = NowPlaying(source="kodi", media_type="movie", title="Original")
    item.images = [
        Artwork(url="https://example/slow.jpg"),
        Artwork(url="https://example/fast.jpg"),
    ]

    start = time.monotonic()
    pipeline.enrich_item(item)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0  # gave up waiting on the slow one well before its 5s sleep
    assert cache.slow_started.wait(timeout=1)  # sanity: the slow fetch did start
    assert ("https://example/fast.jpg", "default") in cache.calls


def test_prefetch_images_one_failing_download_does_not_stop_the_others():
    cache = _RecordingCache(raise_for_url="https://example/broken.jpg")
    pipeline = _pipeline(cache=cache)
    item = NowPlaying(source="kodi", media_type="movie", title="Original")
    item.images = [
        Artwork(url="https://example/broken.jpg"),
        Artwork(url="https://example/ok.jpg"),
    ]

    pipeline.enrich_item(item)  # must not raise

    assert sorted(cache.calls) == [
        ("https://example/broken.jpg", "default"),
        ("https://example/ok.jpg", "default"),
    ]
