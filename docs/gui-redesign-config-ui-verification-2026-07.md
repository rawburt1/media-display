# Config UI browser verification — PR #20 (`gui-redesign`)

*Verified: July 2026, branch `gui-redesign` (HEAD `492dd2c`). Manual smoke test of the
new guided config UI shell in a real (headless) browser, filling the "not yet done" gap
noted in PR #20's test plan.*

## Setup

Ran `python -m mediainfo` locally against an isolated scratch config — separate port
(`18094`) and separate `cache.dir` / `library.db_path` / `overrides.dir` from the live
production container (`media-display-mediainfo-1`, ports 8086/8090-8097) — so the test
run couldn't collide with or mutate real deployment data. Drove it with Playwright
(headless Chromium), watching `console` (errors), `pageerror`, and HTTP responses
(status ≥ 400) throughout.

## What was exercised

- First-run wizard: triggers correctly on an unconfigured setup; step 1 → step 2 source
  picker renders all 18 source types as disabled cards.
- Every sidebar section: Dashboard, Pipeline, Media, Metadata, Appearance, Displays,
  Library, Health.
- A component detail page (MPD) — progressive disclosure form, correct defaults,
  collapsed "Advanced settings", Test connection / Discard / Save actions present.
- Health page "Test connection" on a disabled/unconfigured source — degrades to an
  inline "Unknown source" message rather than crashing or throwing.
- The legacy `/form` "Advanced" page — still reachable and functional alongside the new
  shell.

## Result

Zero browser console errors, zero uncaught page errors, zero HTTP 4xx/5xx responses
across the full walkthrough. Visuals are clean and consistent with the "Midnight Slate"
design pass from Fas 5.

## Caveat found during testing (not a UI bug)

The scratch config initially left `overrides.dir` at its default (`./overrides`,
relative to cwd), which briefly surfaced real production artwork-override entries on
the Library page when run from the repo root. No writes occurred (verified via file
mtimes) — the fix going forward is to always set `cache.dir`, `library.db_path`, and
`overrides.dir` explicitly in any local test config, since all three default relative to
the process's cwd rather than the `--config` path.
