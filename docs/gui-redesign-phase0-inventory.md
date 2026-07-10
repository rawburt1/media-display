# GUI redesign – Fas 0: inventory and classification

This document is the Fas 0 deliverable for the web GUI redesign (Dashboard →
Pipeline → Media → Metadata → Appearance → Displays → Library → Health →
Advanced). It inventories the current config UI, classifies every existing
config section/component type into the new information architecture, and
records the state of the test safety net before any UI code changes begin in
Fas 1.

No production code changes are part of Fas 0 — this file, one new test
fixture, and a handful of new tests are the only changes in this phase.

## 1. Current GUI at a glance

- Single Flask app (`mediainfo/outputs/config_ui.py`), started in a daemon
  thread by `ConfigUiOutput`.
- One SPA-style shell template, `mediainfo/outputs/templates/config_ui/app.html`
  (~2000 lines, Jinja + inline vanilla JS/CSS, no build step, no `static/`
  directory today), plus `library.html` and `overrides.html`.
- Form field metadata (labels, help text, required/secret flags, widgets) is
  generated dynamically from the config dataclasses by
  `mediainfo/outputs/config_schema.py` — not duplicated by hand.
- Config load/save/validate lives in `mediainfo/outputs/config_store.py`
  (`ConfigStore`), reused by every route that reads or writes `config.yaml`.
- Connectivity checks live in `mediainfo/outputs/config_dashboard.py`
  (`test_source` / `test_enricher` / `test_output`).

## 2. Routes → new information architecture

| Route | Method | Today | Maps to (future) |
|---|---|---|---|
| `/` | GET | SPA shell, default section depends on `ui` config (`form` or `dashboard`) | Entry point → **Dashboard** |
| `/form` | GET | SPA shell, "Overview" section preselected | Basis for the new **Dashboard** (see §5) |
| `/dashboard` | GET | SPA shell, "Status" (health-grid) section preselected | Basis for the new **Health** page (see §5) |
| `/library` | GET | Library browser page | **Library** |
| `/overrides` | GET | Artwork overrides page | **Library** (artwork overrides) |
| `/api/schema` | GET | Form schema (labels/help/required/secret/widget) per category | Backing data for **Media/Metadata/Appearance/Displays** detail views |
| `/api/config` | GET | Current values + raw YAML + secrets-set map + hidden types | Backing data for all sections |
| `/api/overview` | GET | Now playing, active source, enabled counts, restart-required, exposed-without-auth | Backing data for **Dashboard** |
| `/api/config/form` | POST | Save one or more dotted-path values | Save path for **Media/Metadata/Appearance/Displays** detail views |
| `/api/config/raw` | POST | Save raw YAML | **Advanced** → raw YAML editor |
| `/api/config/hidden-types` | POST | Hide a plugin type from the picker | **Advanced** / Classic Settings |
| `/api/config/backups`, `/api/config/backups/restore` | GET/POST | List/restore config backups | **Advanced** |
| `/api/restart` | POST | Trigger process restart | **Dashboard** / **Displays** "Apply & Restart" action |
| `/api/hitster-safe` | GET/POST | Hitster-safe mode toggle | **Appearance** |
| `/api/appletv/pair/*` | POST | Apple TV pairing flow | **Media** (Apple TV source detail) |
| `/api/library/stats`, `/search`, `/artist/<id>` | GET | Library browser data | **Library** |
| `/api/overrides`, `/api/overrides/image/<file>` | GET/POST/DELETE | Artwork override CRUD | **Library** |
| `/api/status` | GET | Live health snapshot (proxies the injected health provider) | **Health** |
| `/api/test/source/<name>`, `/api/test/enricher/<name>`, `/api/test/output` | POST | Connectivity checks | "Test connection" action on **Media/Metadata/Displays** component cards |
| `/api/preview/pixoo` | POST | LED image preview | **Displays** (Pixoo detail) |

## 3. Naming collision: `/dashboard` and Overview

The spec's new **Dashboard** (now playing + active pipeline + warnings +
quick actions) does **not** match today's `/dashboard` route. Today:

- `/dashboard` and the `ui: dashboard` config value select the **"Status"**
  section — a live health-grid of every source/output/enricher/idle-provider
  with a per-item "Test connection" button. No now-playing, no pipeline, no
  quick actions.
- The **"Overview"** section (`/form`, backed by `/api/overview` +
  `_compute_overview()` in `config_ui.py`) already has now-playing, active
  source, enabled counts, a "needs attention" warning list, and a quick-action
  row (add source/output, test connections, save, restart). This is much
  closer to the spec's Dashboard.

Decision recorded for Fas 2 (not implemented yet): the new **Dashboard** will
be built as an evolution of the **Overview** section; today's health-grid
("Status") becomes the basis of the new **Health** page. The existing
`/dashboard` route and `ui: dashboard` config value must keep working
(alias/redirect) for backward compatibility — nothing in `config.yaml` should
need to change because of this rename.

## 4. Config section classification

### 4.1 Top-level `config.yaml` keys

| Key | Category | Notes |
|---|---|---|
| `sources` | Media | See §4.2 |
| `outputs` | Displays (mostly) | `outputs.themes` holds Appearance data, see §4.2 |
| `enrichers` | Metadata | See §4.2 |
| `text_enrichers` | Metadata | Lyrics/AI-text plugins (`lrclib`, `mediadata`, `ollama_text`) |
| `idle` | Media | Idle-time media sources (wallpapers/history), same category as `sources` |
| `idle_priority`, `idle_mode` | Media | Idle source selection policy |
| `mediadata` | Library | Unified artwork/lyrics/metadata cache (`MediaDataConfig`) |
| `cache` | Library | Generic artwork/image cache |
| `library` | Library | Music library cache (`MusicLibrary` / library browser) |
| `overrides` | Library | Manual artwork overrides |
| `posters` | Library | Poster store |
| `history` | Library | Playback history |
| `auth` | Advanced | Config UI authentication |
| `logging` | Advanced | Log level/output |
| `alerts` | Health | Failure/health alerting config |
| `poll_interval_seconds`, `rotation_interval_seconds`, `priority`, `backoff_*`, `nothing_playing_grace_seconds` | Advanced | General polling/rotation tuning ("general" schema category) |

### 4.2 Component-type registries

**Sources** (`SOURCE_CONFIG_TYPES`, `mediainfo/config/sources.py`) → **Media**,
all 18: `appletv`, `browser`, `chromecast`, `emby`, `foobar2000`,
`homeassistant`, `jellyfin`, `kodi`, `lms`, `mopidy`, `mpd`, `plex`, `shield`,
`sonos`, `spotify`, `vinyl`, `vlc`, `youtube`.

**Idle sources** (`IDLE_CONFIG_TYPES`, `mediainfo/config/idle.py`) → **Media**
(idle-time variant), all 5: `lastfm`, `library`, `local`, `pexels`, `unsplash`.

**Enrichers** (`ENRICHER_CONFIG_TYPES`, `mediainfo/config/enrichers.py`) →
**Metadata**, all 16: `ai_artwork`, `discogs`, `fanarttv`, `fingerprint`,
`lastfm`, `library`, `lidarr`, `mediadata`, `musicbrainz`, `omdb`, `radarr`,
`sonarr`, `svt`, `thetvdb`, `tmdb`, `wikipedia`.

**Text enrichers** (`TEXT_ENRICHER_CONFIG_TYPES`,
`mediainfo/config/text_enrichers.py`) → **Metadata**, all 3: `lrclib`,
`mediadata`, `ollama_text`.

**Outputs** (`OUTPUT_CONFIG_TYPES`, `mediainfo/config/outputs.py`) →
**Displays**, 11 total: `feed`, `folder`, `info`, `mqtt`, `nest_hub`, `pixoo`,
`ulanzi`, `video`, `web`. Two are special: `config` (`ConfigUiConfig` — the
config UI's own output instance, itself belongs under **System/Advanced**,
not Displays) and `themes` (`ThemesConfig` — an output instance that *hosts*
the appearance theme plugins below; the output wrapper is **Displays**
plumbing, its contents are **Appearance**).

**Display themes** (`THEMES_CONFIG_TYPES`, `mediainfo/config/themes.py`) →
**Appearance**, all 13: `artist_spotlight`, `blurred_background`,
`cast_mosaic`, `color_palette`, `equalizer`, `glow`, `ken_burns`,
`lyrics_ticker`, `media_mosaic`, `progress_bar`, `timeline`, `vinyl`,
`word_cloud`. (No dedicated "Album Art"/"Minimal"/"Movie Poster" registry
entries exist — those names from the spec correspond to the default
appearance when no theme is enabled, plus existing per-media-type rendering,
not separate `THEMES_CONFIG_TYPES` plugins. Fas 2+ should decide whether to
surface these as explicit selectable presets or keep them implicit.)

## 5. Test safety net

`tests/test_config_ui.py` (137 tests after this phase, 133 before) already
covers, end-to-end via `Flask.test_client()` against a real copy of
`config.example.yaml`:

- every GUI route (`/`, `/form`, `/dashboard`, `/library`, `/overrides`)
- every API route listed in §2
- secret masking (`test_schema_marks_secret_fields`,
  `test_schema_does_not_mark_host_as_secret`, plus the new tests below)
- "save doesn't touch unrelated fields/comments"
  (`test_save_form_preserves_untouched_fields`,
  `test_save_form_preserves_comments`,
  `test_save_form_updates_cache_preserves_other_cache_fields`, and others)
- enabled/disabled sources and outputs, multi-instance outputs, missing
  plugin types falling back to defaults

The reusable `config_path` fixture (copies `config.example.yaml`, which
already contains 81 `enabled: true` and 14 `enabled: false` entries plus
realistic secret placeholders like `YOUR_PLEX_TOKEN`) already satisfies the
"realistic mixed enabled/disabled/secrets" fixture requirement — no new
fixture file was needed for that part.

**Gap found and closed in this phase**: the "required field" data contract
(`_REQUIRED_FIELDS` / `_is_required()` in `config_schema.py`, which drives the
Overview page's client-side "missing required settings" warning — computed in
`app.html`'s JS from `/api/schema` + `/api/config`, per
`_compute_overview()`'s own docstring) had no test coverage. Added:

- a new `incomplete_config_path` fixture (`tests/test_config_ui.py`) — a copy
  of `config.example.yaml` with `sources.kodi.host` blanked out while
  `sources.kodi` stays `enabled: true` and its other fields (including the
  secret `sources.kodi.password`) are untouched
- `test_schema_marks_kodi_host_as_required` /
  `test_schema_does_not_mark_non_required_field_as_required` — lock down that
  `/api/schema` reports `required` correctly
- `test_get_config_reports_empty_value_for_missing_required_field` — confirms
  `/api/config` reports the blanked field as empty on an otherwise-enabled
  component
- `test_get_config_does_not_leak_secrets_when_a_sibling_field_is_missing` —
  confirms an unrelated secret on the same component stays masked
  (`secrets_set` still `True`, `values` still `""`) even when a sibling
  required field is missing

This is the exact data contract Fas 1's `UiComponent.status ==
"needs_configuration"` will be computed from, so it's now locked down before
that code is written.

## 6. Baseline verification (run 2026-07-10, on this branch)

```
ruff check mediainfo vinyl_recognizer tests   → clean, no findings
mypy mediainfo                                → clean (exit 0)
pytest                                         → 2026 passed
```

`ruff format --check mediainfo vinyl_recognizer tests` reports 206 files
needing reformatting (including `tests/test_config_ui.py`) — **this predates
this branch**: confirmed via `git stash` that the same 206 files, including
`tests/test_config_ui.py` in its pre-edit state, already fail `ruff format
--check` on `master`. Not fixed here to avoid an unrelated repo-wide diff in
a phase that's supposed to be inventory-only; flagged for a separate,
dedicated formatting pass whenever the maintainer wants one.

## 7. Non-goals of this phase

- No `UiComponent` / `UiPipeline` / `UiDashboard` models (Fas 1).
- No route renaming, no `/dashboard` or `_compute_overview()` behavior change
  (only documented as a decision for Fas 2).
- No new API endpoints.
- No frontend/template changes.
