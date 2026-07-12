"""Artwork/enrichment pipeline: turns a routed source result into an
enriched item ready to push to outputs, and resolves + pushes the
cache-backed image each output should currently show.

Split out of orchestrator.py. `history` is taken as an argument to
prepare_item() rather than captured at construction, because
Orchestrator._history can be reassigned after construction (see tests)
and the very next call must see the change immediately.
"""

from __future__ import annotations

import concurrent.futures
import copy
import logging
import random
import time
from typing import Any, Callable, Dict, List, Optional

from mediainfo.artwork_overrides import ArtworkOverrideStore
from mediainfo.cache import CacheTier, ImageCache
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.enrichers.text_base import TextEnricher
from mediainfo.history import PlaybackHistory
from mediainfo.models import NowPlaying
from mediainfo.orchestrator_state import _RotationState, _RouteGroup
from mediainfo.outputs.base import Output
from mediainfo.poster_store import PosterStore

logger = logging.getLogger(__name__)

# Default per-enricher wall-clock deadline (C2 in
# docs/architecture-usability-review-2026-07.md): enrichers still run
# strictly one at a time, in their configured order - several of them read
# NowPlaying.images/ids left by an earlier one (svt.py's TVDB-id check,
# fanarttv.py's insert(0, ...) priority), so genuine concurrency would
# change behavior, not just speed it up. This only bounds the worst case: a
# single hung/slow enricher no longer blocks every display indefinitely: the
# tick gives up waiting after this many seconds and moves on to the next
# enricher. The abandoned call keeps running in the background and may still
# mutate the item shortly after - a rare, deliberately accepted tradeoff for
# the common case of a network call that simply never returns.
_DEFAULT_ENRICHMENT_DEADLINE_SECONDS = 30.0


def _enricher_deadline(enricher: Any, default: float) -> float:
    """An enricher's own `config.timeout_seconds`, if it has one, takes
    priority over the shared default - e.g. ai_artwork/ollama_text already
    expose a deliberately generous timeout for slow-but-bounded local
    inference, and shouldn't be cut off by a default tuned for ordinary
    HTTP lookups.
    """
    configured = getattr(getattr(enricher, "config", None), "timeout_seconds", None)
    if isinstance(configured, (int, float)) and not isinstance(configured, bool):
        return float(configured)
    return default


class _ArtworkPipeline:
    def __init__(
        self,
        enrichers: List[ArtworkEnricher],
        cache: ImageCache,
        rotation_interval_seconds: float,
        call_output: Callable[..., None],
        safe_call: Callable[..., None],
        poster_store: Optional[PosterStore] = None,
        overrides: Optional[ArtworkOverrideStore] = None,
        text_enrichers: Optional[List[TextEnricher]] = None,
        enrichment_deadline_seconds: float = _DEFAULT_ENRICHMENT_DEADLINE_SECONDS,
    ):
        self.enrichers = enrichers
        self.text_enrichers = text_enrichers or []
        self.cache = cache
        self.rotation_interval_seconds = rotation_interval_seconds
        self._call_output = call_output
        self._safe_call = safe_call
        self._poster_store = poster_store
        self._overrides = overrides
        self.enrichment_deadline_seconds = enrichment_deadline_seconds

    def prepare_item(
        self,
        groups: List[_RouteGroup],
        group: _RouteGroup,
        item: Optional[NowPlaying],
        prepared: Dict[tuple, NowPlaying],
        history: Optional[PlaybackHistory],
    ) -> Optional[NowPlaying]:
        """Return the item the caller should route to `group`, enriching a
        genuinely new item exactly once per tick even when several groups
        pick it.

        Sources return a fresh (unenriched) NowPlaying every poll. For a
        group already playing the same identity that's fine - the SAME_ITEM
        path only reads position/duration off it. For a group *newly*
        binding it, prefer (in order): the object another group picking it
        this tick already enriched, the already-enriched `current` of a
        group that was playing it before this tick, or - only when neither
        exists - enrich the fresh object now.
        """
        if item is None:
            return None
        if group.current is not None and group.current.identity == item.identity:
            return item
        if item.identity in prepared:
            return prepared[item.identity]
        donor = next(
            (
                g.current
                for g in groups
                if g.current is not None and g.current.identity == item.identity
            ),
            None,
        )
        if donor is not None:
            # Keep the donor's enrichment; carry over the fresh poll's
            # playback position (the donor group's own SAME_ITEM refresh
            # would do this anyway, but group order isn't guaranteed).
            donor.position_seconds = item.position_seconds
            donor.duration_seconds = item.duration_seconds
            prepared[item.identity] = donor
            return donor
        self.enrich_item(item)
        # Exactly here - a genuinely new item, once per identity per tick,
        # after enrichment (so the logged artwork URL is the enriched
        # pick). The donor/rebind paths above deliberately don't log:
        # the item was already playing, just on another group.
        if history is not None:
            history.record(item)
        prepared[item.identity] = item
        return item

    def enrich_item(self, now_playing: NowPlaying) -> None:
        for enricher in self.enrichers:
            self._run_enricher_with_deadline(enricher, enricher.enrich, now_playing)
        self.apply_poster_store(now_playing)
        self.apply_artwork_override(now_playing)
        for text_enricher in self.text_enrichers:
            self._run_enricher_with_deadline(text_enricher, text_enricher.enrich, now_playing)

    def _run_enricher_with_deadline(
        self, enricher: Any, func: Callable[[NowPlaying], None], now_playing: NowPlaying
    ) -> None:
        """Run one enricher (already wrapped in the caller's usual
        exception isolation via self._safe_call) but give up waiting past
        its deadline instead of blocking the rest of this tick - and every
        display - on it. See _DEFAULT_ENRICHMENT_DEADLINE_SECONDS above for
        why enrichers still run strictly in order rather than concurrently.
        """
        deadline = _enricher_deadline(enricher, self.enrichment_deadline_seconds)
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._safe_call, func, now_playing)
        try:
            future.result(timeout=deadline)
        except concurrent.futures.TimeoutError:
            logger.warning(
                "%s exceeded its %.0fs enrichment deadline - moving on without "
                "waiting for it; it may still finish and update this item shortly after",
                type(enricher).__name__,
                deadline,
            )
        finally:
            pool.shutdown(wait=False)

    def apply_poster_store(self, now_playing: NowPlaying) -> None:
        """If a static poster is configured for this title (and optionally
        source), replace enriched artwork with it. Artwork overrides (see
        apply_artwork_override) run after this and therefore win.
        """
        if self._poster_store is None:
            return
        try:
            poster = self._poster_store.get(now_playing)
        except Exception:
            logger.exception("Error checking poster store for %s", now_playing.title)
            return
        if poster is not None:
            logger.debug("Using stored poster for %s", now_playing.title)
            now_playing.images = [poster]

    def apply_artwork_override(self, now_playing: NowPlaying) -> None:
        """If a manual override is pinned for this title/subtitle (see
        artwork_overrides.py), replace whatever enrichment found with just
        that one image - a deliberate user choice overrides automatic
        enrichment entirely, rather than just joining the rotation pool.
        """
        if self._overrides is None:
            return
        try:
            override = self._overrides.get(now_playing.title, now_playing.subtitle)
        except Exception:
            logger.exception("Error checking artwork overrides for %s", now_playing.title)
            return
        if override is not None:
            now_playing.images = [override]

    def build_rotation_states(
        self, num_images: int, output_indices: List[int]
    ) -> Dict[int, _RotationState]:
        """Build one _RotationState per output in `output_indices`, sharing
        a single shuffled order but starting each output at a different
        position in it - so outputs never start on the same picture (as
        long as there are at least as many images as outputs) instead of
        leaving that to chance via independent per-output shuffles, which
        can (and visibly does, with a modest-sized image pool)
        coincidentally collide.

        Each output's rotation clock is also given its own random phase
        within the interval, so they don't all advance to their next image
        at the same instant either - otherwise every output would become
        "due" to rotate on the exact same tick forever after.
        """
        order = list(range(num_images))
        random.shuffle(order)
        now = time.monotonic()
        states = {}
        for offset, index in enumerate(output_indices):
            jitter = random.uniform(0, self.rotation_interval_seconds)
            states[index] = _RotationState(
                order=order, position=offset % num_images, last_rotation=now - jitter
            )
        return states

    def show_image_for_output(self, group: _RouteGroup, index: int, output: Output) -> None:
        """Resolve and push the output's current rotation pick - falling
        through the rest of the pool (in rotation order) if that pick fails
        to fetch (e.g. rejected by the cache's minimum-size filter, or a
        download error), rather than leaving the output showing nothing
        until its next scheduled rotation, up to rotation_interval_seconds
        later.
        """
        assert group.current is not None  # only called while something is playing
        state = group.rotation_state[index]
        images = group.current.images
        tier: CacheTier = "music" if group.current.media_type == "music" else "default"

        skip_artist_photos = output.music_album_art_only and group.current.media_type == "music"
        skip_wordclouds = not output.show_wordclouds
        for attempt in range(len(images)):
            artwork = images[state.order[(state.position + attempt) % len(state.order)]]
            if skip_artist_photos and artwork.is_artist_photo:
                continue
            if skip_wordclouds and artwork.is_wordcloud:
                continue
            try:
                image_path = self.cache.get_path(artwork, tier=tier)
                if image_path is None:
                    continue
                image_path = self.cache.get_transformed_path(image_path, output.transform_pipeline)
            except Exception:
                logger.exception("Failed to fetch artwork %s", artwork.url)
                continue

            # A copy, not group.current itself: outputs (several of them
            # Flask apps serving requests on their own threads) hold onto
            # whatever they're handed here indefinitely, while group.current
            # keeps being mutated in place by the orchestrator thread on
            # every later tick (_refresh_position's position/duration
            # updates, a future _refresh_artwork() re-enrichment) - handing
            # out the live object would be a data race by construction. A
            # shallow copy is enough: the fields that get mutated in place
            # after the fact (position_seconds, duration_seconds) are plain
            # scalars on the copy, decoupled from the original.
            self._call_output(index, output.update, copy.copy(group.current), artwork, image_path)
            return

        logger.warning(
            "No fetchable artwork for %s (%d candidate(s) all failed) - clearing output to idle",
            group.current.title,
            len(images),
        )
        self._call_output(index, output.on_idle)
