# Architecture Decision Records

This directory holds ADRs for `media-display` (package `mediainfo`): short,
numbered records of decisions whose *rationale* is long enough that it would
otherwise bloat a module docstring and rot silently once nobody remembers
why (see `docs/architecture-usability-review-2026-07.md`'s Phase 9 and its
N6 recommendation).

Not every design choice needs one. Reach for an ADR when a docstring's
rationale would run long enough to bury the module's actual API/behavior
under "why" — the module keeps a short orientation summary and a link here
for the full story. Most modules should keep their rationale inline; this
is for the handful of essay-length exceptions.

## Format

Each ADR is a single Markdown file, `NNNN-short-title.md`:

- **Status** — Accepted, Superseded (by ADR NNNN), or Deprecated.
- **Context** — the problem/constraints that forced a choice.
- **Decision** — what was chosen.
- **Consequences** — the trade-offs, known limitations, and what this
  decision deliberately did *not* solve.

Once accepted, treat the Context/Decision as historical record — don't edit
them to match later changes. If the decision changes, write a new ADR that
supersedes the old one and mark the old one's Status accordingly.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-config-ui-two-shell-migration-and-request-lifecycle.md) | Config UI: two-shell migration, schema-driven forms, and secret/restart semantics | Accepted |
| [0002](0002-media-data-store-layout.md) | Unified on-disk media metadata/artwork/lyrics store: layout and freshness policy | Accepted |
