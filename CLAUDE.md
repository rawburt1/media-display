# CLAUDE.md

Project-specific guidance for Claude when working in this repository.

## 1. Project overview

`media-display` is a Python application that polls “now playing” media sources on a home network and displays artwork, posters, metadata, text, and idle visuals on different outputs.

The package name is `mediainfo`.

Core concepts:

- **Sources** read current playback/media state.
- **Enrichers / metadata providers** add artwork, posters, fanart, music/movie/TV metadata, lyrics, or local library data.
- **Outputs / displays** render or publish current media state to screens, files, MQTT, web pages, feeds, or other targets.
- **Idle providers** provide fallback visuals when no media is playing.
- **Config UI** backend is mainly in `mediainfo/configui/` (a thin `ConfigUiOutput` adapter remains at `mediainfo/outputs/config_ui.py`); templates/static assets stay at `mediainfo/outputs/templates/config_ui/` and `mediainfo/outputs/static/config_ui/`.

Favor reliability, clear behavior, and safe incremental changes over large rewrites.

## 2. Non-negotiable constraints

- **No real network in tests**: always mock external services, browsers, devices, and APIs.
- **No secrets exposure**: never expose passwords, API keys, tokens, cookies, refresh tokens, or credentials.
- **Config stability**: do not break or restructure the root YAML config unless explicitly requested.
- **Small changes first**: prefer reviewable, testable changes over large rewrites.
- **Preserve behavior**: refactors must keep existing behavior unless a change is deliberate, documented, and tested.
- **Graceful degradation**: missing dependencies, API keys, devices, or services must not crash the app.
- **New integrations disabled by default** unless explicitly requested otherwise.

## 3. Development commands

```bash
ruff check --fix mediainfo vinyl_recognizer tests
ruff format mediainfo vinyl_recognizer tests
mypy mediainfo
pytest
```

Run narrower tests first if useful, then run the relevant full test suite.

## 4. Repository landmarks

- `mediainfo/orchestrator.py` – polling, routing, orchestration.
- `mediainfo/sources/` – source integrations.
- `mediainfo/enrichers/` – metadata and artwork enrichment.
- `mediainfo/outputs/` – output/display integrations.
- `mediainfo/configui/` – config UI backend (schema generation, config store, dashboard/pipeline builders).
- `mediainfo/outputs/templates/config_ui/` – config UI templates.
- `mediainfo/imaging/` – image processing (LED prep, text removal, transforms, colors, lyrics word clouds).
- `mediainfo/stores/` – persistence (media data store, poster store, text cache, artwork overrides, history, music library).
- `mediainfo/idle/` – idle providers.
- `tests/` – unit and regression tests.

If a file mixes concerns, extract small helpers instead of rewriting it all at once.

## 5. Engineering principles

1. Work iteratively.
2. Add or update tests with meaningful changes.
3. Reuse existing config load/save/validate logic.
4. Reuse existing secret-masking behavior.
5. Avoid duplicate parsing, validation, or persistence paths.
6. Avoid heavy dependencies unless clearly justified.
7. Keep public APIs and config keys stable.
8. Prefer typed, explicit internal models for new interfaces.
9. Prefer clear user-facing errors over raw exceptions.
10. Keep fallback behavior available during migrations.
11. Document new config options and update examples.
12. Do not silently overwrite unknown config keys.

## 6. Configuration and secrets

- Preserve YAML structure and semantics.
- Add safe defaults for optional settings.
- Validate required fields with helpful messages.
- Do not replace existing secrets with blanks or placeholders.
- Modify only the intended config path.
- Keep config writes deterministic and test-covered.
- Mask secret-like fields: `password`, `token`, `access_token`, `refresh_token`, `api_key`, `client_secret`, `secret`, `cookie`, `authorization`.
- Secrets must not appear in logs, API responses, rendered templates, browser-visible payloads, test snapshots, fixtures, or normal user-facing errors.

## 7. Testing rules

Tests must not require real devices or services such as Kodi, Plex, Sonos, Spotify, Home Assistant, Pixoo, or external metadata APIs.

Important test coverage:

- config load/save/validate
- no secret leaks
- disabled components stay inactive
- missing dependencies are handled
- network/API failures are mocked
- timeouts and error states
- existing API/UI routes still work when touched
- config changes affect only intended paths
- user-facing errors are understandable

## 8. Sources, enrichers, outputs

When working on sources:

- Normalize output into the existing playback/media model.
- Handle playing, paused, stopped, idle, and unknown states.
- Treat missing metadata as normal.
- Include timeout handling and health/test-connection behavior where appropriate.
- Do not let one broken source crash the whole app.

When working on enrichers:

- Use available local data before external lookups where supported.
- Handle missing API keys clearly.
- Avoid repeated lookups when cache behavior exists.
- Do not fail the whole pipeline because one enricher fails.
- Mock external APIs in tests.

When working on outputs:

- Handle device and network failures gracefully.
- Do not crash orchestration because one output fails.
- Make restart requirements explicit when applicable.
- Keep output-specific filters/transforms isolated.
- Clean up temporary files, streams, and generated test artifacts.

## 9. Web UI rules

- Keep it understandable for non-technical home users.
- Do not remove existing configuration capabilities without a fallback.
- Keep advanced/raw configuration access if it already exists.
- Use clear labels and actionable error messages.
- Never expose secrets in HTML, JavaScript, or JSON.
- Reuse existing backend validation and save logic.
- Test changed routes, API responses, and config persistence.

## 10. File and cache handling

- Use safe path handling.
- Centralize filename/path normalization.
- Prevent path traversal.
- Create directories only where appropriate.
- Write temporary files first, then replace atomically where practical.
- Do not overwrite working files when refresh/download fails.
- Keep behavior deterministic and testable.

## 11. Completion checklist

Before finishing, verify formatting, linting, relevant type checks, and tests. Also verify no secrets are exposed, config compatibility is preserved, old behavior still works, docs/examples are updated when needed, new features are disabled by default unless intended, and no real network/devices are required in tests.

## 12. Summary principle

Build and maintain `media-display` as a reliable home media display application: stable config, safe secrets, mocked tests, small changes, clear errors, and graceful degradation.

<!-- rtk-instructions v2 -->
# RTK (Rust Token Killer) - Token-Optimized Commands

## Golden Rule

**Always prefix commands with `rtk`**. If RTK has a dedicated filter, it uses it. If not, it passes through unchanged. This means RTK is always safe to use.

**Important**: Even in command chains with `&&`, use `rtk`:
```bash
# ❌ Wrong
git add . && git commit -m "msg" && git push

# ✅ Correct
rtk git add . && rtk git commit -m "msg" && rtk git push
```

## RTK Commands by Workflow

### Build & Compile (80-90% savings)
```bash
rtk cargo build         # Cargo build output
rtk cargo check         # Cargo check output
rtk cargo clippy        # Clippy warnings grouped by file (80%)
rtk tsc                 # TypeScript errors grouped by file/code (83%)
rtk lint                # ESLint/Biome violations grouped (84%)
rtk prettier --check    # Files needing format only (70%)
rtk next build          # Next.js build with route metrics (87%)
```

### Test (60-99% savings)
```bash
rtk cargo test          # Cargo test failures only (90%)
rtk go test             # Go test failures only (90%)
rtk jest                # Jest failures only (99.5%)
rtk vitest              # Vitest failures only (99.5%)
rtk playwright test     # Playwright failures only (94%)
rtk pytest              # Python test failures only (90%)
rtk rake test           # Ruby test failures only (90%)
rtk rspec               # RSpec test failures only (60%)
rtk test <cmd>          # Generic test wrapper - failures only
```

### Git (59-80% savings)
```bash
rtk git status          # Compact status
rtk git log             # Compact log (works with all git flags)
rtk git diff            # Compact diff (80%)
rtk git show            # Compact show (80%)
rtk git add             # Ultra-compact confirmations (59%)
rtk git commit          # Ultra-compact confirmations (59%)
rtk git push            # Ultra-compact confirmations
rtk git pull            # Ultra-compact confirmations
rtk git branch          # Compact branch list
rtk git fetch           # Compact fetch
rtk git stash           # Compact stash
rtk git worktree        # Compact worktree
```

Note: Git passthrough works for ALL subcommands, even those not explicitly listed.

### GitHub (26-87% savings)
```bash
rtk gh pr view <num>    # Compact PR view (87%)
rtk gh pr checks        # Compact PR checks (79%)
rtk gh run list         # Compact workflow runs (82%)
rtk gh issue list       # Compact issue list (80%)
rtk gh api              # Compact API responses (26%)
```

### JavaScript/TypeScript Tooling (70-90% savings)
```bash
rtk pnpm list           # Compact dependency tree (70%)
rtk pnpm outdated       # Compact outdated packages (80%)
rtk pnpm install        # Compact install output (90%)
rtk npm run <script>    # Compact npm script output
rtk npx <cmd>           # Compact npx command output
rtk prisma              # Prisma without ASCII art (88%)
```

### Files & Search (60-75% savings)
```bash
rtk ls <path>           # Tree format, compact (65%)
rtk read <file>         # Code reading with filtering (60%)
rtk grep <pattern>      # Search grouped by file (75%). Format flags (-c, -l, -L, -o, -Z) run raw.
rtk find <pattern>      # Find grouped by directory (70%)
```

### Analysis & Debug (70-90% savings)
```bash
rtk err <cmd>           # Filter errors only from any command
rtk log <file>          # Deduplicated logs with counts
rtk json <file>         # JSON structure without values
rtk deps                # Dependency overview
rtk env                 # Environment variables compact
rtk summary <cmd>       # Smart summary of command output
rtk diff                # Ultra-compact diffs
```

### Infrastructure (85% savings)
```bash
rtk docker ps           # Compact container list
rtk docker images       # Compact image list
rtk docker logs <c>     # Deduplicated logs
rtk kubectl get         # Compact resource list
rtk kubectl logs        # Deduplicated pod logs
```

### Network (65-70% savings)
```bash
rtk curl <url>          # Compact HTTP responses (70%)
rtk wget <url>          # Compact download output (65%)
```

### Meta Commands
```bash
rtk gain                # View token savings statistics
rtk gain --history      # View command history with savings
rtk discover            # Analyze Claude Code sessions for missed RTK usage
rtk proxy <cmd>         # Run command without filtering (for debugging)
rtk init                # Add RTK instructions to CLAUDE.md
rtk init --global       # Add RTK to ~/.claude/CLAUDE.md
```

## Token Savings Overview

| Category | Commands | Typical Savings |
|----------|----------|-----------------|
| Tests | vitest, playwright, cargo test | 90-99% |
| Build | next, tsc, lint, prettier | 70-87% |
| Git | status, log, diff, add, commit | 59-80% |
| GitHub | gh pr, gh run, gh issue | 26-87% |
| Package Managers | pnpm, npm, npx | 70-90% |
| Files | ls, read, grep, find | 60-75% |
| Infrastructure | docker, kubectl | 85% |
| Network | curl, wget | 65-70% |

Overall average: **60-90% token reduction** on common development operations.
<!-- /rtk-instructions -->