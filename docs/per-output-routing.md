# Per-output source routing — design plan

Status: **planned, not implemented.** Written 2026-07-02, against the
codebase as of PR #11. File/line references below will drift; the
structural claims (what holds single-item state, what iterates all
outputs) are the durable part.

## Goal

Today the orchestrator picks **one** winning source globally, so a Sonos
playing in the kitchen and Kodi playing in the living room can't both be
shown — the lower-priority one is invisible, and an output whose filter
rejects the winner just goes idle. After this change, each output shows
the highest-priority active item *it* accepts: the kitchen display binds
to Sonos while the living-room display follows Kodi.

## Semantics (the decisions that matter most)

**1. Route by item, not by source.** Each output shows the
highest-priority *poll result* that passes its content filter. This
deliberately includes media-type filters, not just source filters: an
`allow_media_types: [music]` kitchen display binds to Sonos even while
Kodi (higher priority) plays a movie. Routing by static source lists
alone would miss this, because a source's media type varies per item
(Kodi plays both movies and music).

**2. Route groups.** Outputs with the same *content-rule signature* —
normalized `allow/deny_media_types` + `allow/deny_sources` — form one
group sharing an item, its enrichment, and its grace-period state.
`active_hours` is deliberately **excluded** from the signature: it's
time-varying and decides *whether* an output displays, not *what* it
would show. It stays a per-output display gate through the existing
`_filtered_outputs` / `_recheck_filters` mechanism in orchestrator.py,
which already handles mid-play transitions.

**3. Zero-filter compatibility.** With no filters configured, every
output has the empty signature → one group → behavior identical to
today. This is the key regression guarantee and the first test to write.

**4. Behavior change for existing filter users — call it out.** Today an
output that denies the winning source goes idle even when a
lower-priority source is *also* playing; after this, it shows that
lower-priority source. That matches the natural reading of "deny
spotify" (≠ "show nothing"), so the recommendation is to ship it as the
new default with a CHANGELOG/README note rather than behind a flag.
`idle_when_filtered` keeps meaning "go idle when nothing passes."

Open question: if the old semantics need to be preservable, a
`routing: global` escape hatch is cheap to add — wait until someone asks.

**5. Hitster-safe stays global**: applied to each poll result (music →
treated as nothing) *before* routing, in what is now
`_resolve_now_playing` in orchestrator.py.

## What has to change, file by file

### `orchestrator.py` — the bulk of the work

- New `_RouteGroup` dataclass: `signature`, `output_indices`,
  `current: Optional[NowPlaying]`,
  `rotation_state: Dict[int, _RotationState]`,
  `nothing_playing_since: Optional[float]`. Groups are computed once in
  `__init__` from `output.config` (outputs are fixed for process
  lifetime, so this is static).
- `_poll_sources()` currently returns the **first** active result. It
  becomes "poll down the priority list, offering each result to every
  still-unsatisfied group, until all groups are satisfied or sources are
  exhausted." Per-source backoff bookkeeping is untouched — it's already
  keyed by source name, not by winner. Note this polls *more* than today
  when something is playing (today lower sources aren't polled at all
  once a winner exists), but that's the same load as the current
  all-idle case, so it's within the existing behavior envelope. Optional
  later optimization: statically prune sources no unsatisfied group
  could accept via `allow/deny_sources` (media-type rules can't prune
  statically).
- `_tick()` becomes a loop over groups, each running the existing
  classify → rotate/idle/new-item logic (`_classify`,
  `_refresh_position`, `_maybe_rotate`, `_handle_new_item`) scoped to
  the group's outputs. `_classify` is already pure and takes both sides
  explicitly — it barely changes.
- **Enrichment dedupe:** two groups can pick the same item (overlapping
  filters). Enrich once per distinct `NowPlaying.identity` per tick and
  share the object — that's what happens today with one group, and
  `identity` deliberately excludes images, so sharing is safe. Note:
  enrichment of two *different* new items in one tick is sequential and
  doubles worst-case tick latency; acceptable for v1 (realistically 2–3
  groups), parallelize later if it ever hurts.
- Poster store / artwork overrides / title stripping: applied per item,
  unchanged logic.

### `orchestrator_idle.py` — scope idle to unbound outputs

- `_IdleBatchManager` pushes to **all** outputs today
  (`_push_current_batch`, `rotate`, `_notify_outputs` all iterate
  `self.outputs`). It needs an `idle_indices: set[int]` parameter on
  `show()` — outputs whose group currently has an item must not receive
  idle pushes. Its rotation state is already keyed by output index, so
  this is a filter in three loops, not a redesign.
- `clear_if_stale()` is a trap: it clears the batch as soon as *a*
  playing item has artwork, which would blank the still-idle outputs of
  other groups. Change to: clear only when **no** group is idle. This is
  the subtlest behavioral detail in the plan and needs its own test.

### `orchestrator_health.py` / `health.py` / dashboard — surface the routing

- `active_source_name` becomes a per-group map; keep `active_source` in
  the JSON as the highest-priority active item (backward compat for
  anything scraping `/health`), and add `outputs[i].now_playing` (or a
  `routes` section) so the dashboard can show which source each output
  is bound to. `get_health()`'s single `now_playing` block likewise
  stays but gains a per-output view.

### No changes needed

`output_filter.py` (`passes_filter` is already the routing predicate),
the outputs themselves (each still receives one item via the existing
`on_new_item`/`update`/`on_idle` contract — the web output's
multi-client rotation is untouched), config schema (reuses the filter
fields as-is), wiring, alerting, cache.

## Phasing (each lands green on its own)

1. **Pure refactor, no behavior change:** introduce `_RouteGroup`, put
   *all* outputs in one group, move
   `_current`/`_rotation_state`/`_nothing_playing_since` into it. Keep
   `orch._current` as a property aliasing the single group during this
   phase so the ~1,800-line `test_orchestrator.py` needs near-zero
   edits; drop the alias in phase 3 when tests are touched anyway.
2. **Polling:** `_poll_sources` → returns ordered active results with
   the satisfaction-driven early stop. With one group this still
   short-circuits at the first hit, so behavior is unchanged and
   existing poll/backoff tests pass.
3. **Real routing:** group construction from filter signatures,
   per-group ticks, enrichment dedupe, idle scoping + `clear_if_stale`
   fix. This is the phase with the new tests.
4. **Health/dashboard/docs:** per-output binding in `/health` and the
   status dashboard; README + CHANGELOG note about the filter-semantics
   change.

## Test plan (new `tests/test_orchestrator_routing.py`)

- No-filter config: single group, existing behavior (belt-and-braces
  alongside the untouched legacy suite).
- Two sources active, one output allows only the lower-priority one →
  both outputs show their own source simultaneously.
- Media-type routing: music-only output binds past a higher-priority
  movie.
- Same item selected by two groups → enrichers called once.
- Higher-priority source appears mid-play → only groups that accept it
  switch; others keep their item.
- Grace period is per group: source A blipping doesn't flash group B.
- One group idle, one playing: idle wallpapers go only to the idle
  group's outputs; `clear_if_stale` doesn't blank them when the other
  group starts playing.
- `active_hours` still gates display without changing group membership
  (out-of-hours output goes idle, its group's other outputs unaffected).

## Rough size

Phases 1–2 are mechanical (~a day including test churn). Phase 3 is the
real work — orchestrator tick restructure plus the idle-scoping
subtleties. Phase 4 is small. The dominant cost is test migration in
`test_orchestrator.py`, which is why phase 1 keeps the `_current` alias.

## Open questions

- Ship the filter-semantics change default-on (recommended) or behind a
  `routing:` config flag?
- Dashboard per-output bindings in v1, or defer to a follow-up?
