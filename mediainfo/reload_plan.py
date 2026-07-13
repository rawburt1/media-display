"""Decides which subsystems actually need rebuilding on a config-file
hot-reload (N7 in docs/architecture-usability-review-2026-07.md).

Before this module existed, __main__.py's reload loop tore down and
rebuilt every source, enricher, text enricher, and idle provider - and
restarted the whole orchestrator thread - on *every* reload, even when the
changed section was something as narrow as history.max_entries. That's
wasteful (sources reconnect to real devices/services for no reason) and
briefly disruptive (a moment of "nothing playing" on every output while
sources reconnect), for changes that had nothing to do with them.

compute_reload_plan() is a pure function of (old, new) Config, with no
knowledge of the actual source/enricher/cache objects - so the dependency
logic itself is cheaply unit-testable without constructing any real
subsystem. __main__.py's reload loop uses the resulting ReloadPlan to
decide what to rebuild and what to leave running untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

from mediainfo.config import Config


@dataclass(frozen=True)
class ReloadPlan:
    cache_dirty: bool
    sources_dirty: bool
    enrichers_dirty: bool
    text_enrichers_dirty: bool
    idle_dirty: bool
    mediadata_store_dirty: bool
    library_dirty: bool
    overrides_dirty: bool
    posters_dirty: bool
    history_dirty: bool
    # True whenever anything the running Orchestrator was constructed from
    # changed - any of the above collaborators being dirty, or one of the
    # scalar values (poll_interval_seconds, backoff, ...) passed straight
    # into its constructor. The orchestrator thread only needs to be
    # stopped and rebuilt when this is True.
    orchestrator_dirty: bool


def compute_reload_plan(old: Config, new: Config) -> ReloadPlan:
    """Compare *old* and *new* Config and say which mediainfo.wiring
    build_*() calls can be skipped in favor of reusing the previous
    object.

    Each `*_dirty` flag reflects every real dependency of the
    corresponding mediainfo.wiring build_*() function, not just "did its
    own config section change" - e.g. build_enrichers() takes `library`
    and `mediadata_store` as arguments and derives a cache-dir path from
    config.cache, so enrichers_dirty is True if any of *those* changed
    too, even when config.enrichers itself is untouched. Erring toward
    "dirty" is always the safe direction here: rebuilding something that
    didn't strictly need it just costs a bit of reconnect time, but
    reusing an object that still holds a stale reference to a
    since-replaced collaborator (e.g. a closed MusicLibrary) would be a
    real bug.
    """
    cache_changed = new.cache != old.cache
    sources_changed = new.sources != old.sources or new.priority != old.priority
    enrichers_changed = new.enrichers != old.enrichers
    text_enrichers_changed = new.text_enrichers != old.text_enrichers
    idle_changed = (
        new.idle != old.idle
        or new.idle_priority != old.idle_priority
        or new.idle_mode != old.idle_mode
    )
    mediadata_changed = new.mediadata != old.mediadata
    library_changed = new.library != old.library
    overrides_changed = new.overrides != old.overrides
    posters_changed = new.posters != old.posters
    history_changed = new.history != old.history
    orchestrator_scalars_changed = (
        new.poll_interval_seconds != old.poll_interval_seconds
        or new.rotation_interval_seconds != old.rotation_interval_seconds
        or new.backoff_initial_seconds != old.backoff_initial_seconds
        or new.backoff_max_seconds != old.backoff_max_seconds
        or new.nothing_playing_grace_seconds != old.nothing_playing_grace_seconds
        or new.enrichment_deadline_seconds != old.enrichment_deadline_seconds
        or new.alerts != old.alerts
    )

    # build_mediadata_store() reads config.mediadata, config.enrichers (its
    # own "mediadata" entry, plus discogs/tmdb/fanarttv/lastfm credentials)
    # and config.text_enrichers (its own "mediadata" entry), and is
    # constructed with the `cache` object itself - so any of those, not
    # just config.mediadata, requires a rebuild.
    mediadata_store_dirty = (
        cache_changed or mediadata_changed or enrichers_changed or text_enrichers_changed
    )

    # build_enrichers() takes `library` (for "library"-capability
    # enrichers), `mediadata_store` (for "mediadata"-capability
    # enrichers), and derives a cache-dir path from config.cache (for
    # "cache_dir"-capability enrichers, e.g. ai_artwork).
    enrichers_dirty = enrichers_changed or library_changed or cache_changed or mediadata_store_dirty

    # build_text_enrichers() takes `mediadata_store` and builds a fresh
    # TextCache from config.cache on every call.
    text_enrichers_dirty = text_enrichers_changed or cache_changed or mediadata_store_dirty

    # build_idle_source() takes `library`.
    idle_dirty = idle_changed or library_changed

    # The Orchestrator instance is constructed from every one of these -
    # any of them changing means the running instance would otherwise hold
    # a stale collaborator (sources/enrichers/idle_source/cache/overrides/
    # poster_store/history) or a constructor-only scalar it can't be told
    # about after the fact, so it needs to be stopped and rebuilt.
    orchestrator_dirty = (
        sources_changed
        or enrichers_dirty
        or text_enrichers_dirty
        or idle_dirty
        or cache_changed
        or overrides_changed
        or posters_changed
        or history_changed
        or orchestrator_scalars_changed
    )

    return ReloadPlan(
        cache_dirty=cache_changed,
        sources_dirty=sources_changed,
        enrichers_dirty=enrichers_dirty,
        text_enrichers_dirty=text_enrichers_dirty,
        idle_dirty=idle_dirty,
        mediadata_store_dirty=mediadata_store_dirty,
        library_dirty=library_changed,
        overrides_dirty=overrides_changed,
        posters_dirty=posters_changed,
        history_dirty=history_changed,
        orchestrator_dirty=orchestrator_dirty,
    )
