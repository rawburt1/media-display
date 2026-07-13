# `/health` API reference

`GET /health` (also `/health/ready`, on the web output) returns a JSON
payload describing overall app health and the status of every source,
output, enricher, and idle wallpaper source. It's built by
`mediainfo.health.make_health_provider()` and used by three different
kinds of consumer:

- Anything polling `/health` directly for monitoring (uptime checks, Home
  Assistant, a dashboard you build yourself).
- `outputs/mqtt.py`, which republishes a derived `ON`/`OFF` problem flag to
  `{topic}/health/state`.
- The config UI's new dashboard (`outputs/ui_builder.py`), which reads
  this same data to render per-component status cards - it does not
  recompute status itself.

`Accept: text/html` on the same route instead renders a human-readable
HTML dashboard (`web/health.html`); `GET /health/live` is a separate,
always-minimal `{"status": "ok"}` liveness probe for the Docker
healthcheck and is not part of this schema.

## Versioning contract

`schema_version` (see `mediainfo/health.py`'s `HEALTH_SCHEMA_VERSION`)
identifies this document's version. The rule mirrors config.yaml's
`config_version` (see README.md):

- **Not breaking, no version bump**: adding a new top-level field, adding
  a new field to a source/output/enricher/idle-source entry, or adding a
  new entry. Every entry below is deliberately open-ended - sources,
  outputs, and enrichers each merge in their own `health_check()`
  return value and/or non-secret config fields (`config_detail_fields()`),
  so the exact key set of an individual entry varies by plugin type and
  is expected to grow. Consumers must tolerate unknown keys.
- **Breaking, bumps the version**: removing or renaming a field
  documented below, or changing its type or meaning (e.g. a field that
  used to be a string becoming a number).

## Top-level fields

| Field | Type | Notes |
|---|---|---|
| `status` | string | `"ok"` once the orchestrator has started; `"starting"` briefly during boot, before the very first tick. |
| `schema_version` | integer | This document's version - see above. |
| `uptime_seconds` | number | Seconds since the orchestrator started. |
| `poll_interval_seconds` | number | Current `poll_interval_seconds` config value. |
| `rotation_interval_seconds` | number | Current `rotation_interval_seconds` config value. |
| `now_playing` | object \| null | The current highest-priority bound item (pre-routing global winner - see `output_now_playing`-style per-output binding on each `outputs[]` entry for per-output routing setups). `null` when nothing is playing. Shape: `{"source", "media_type", "title", "subtitle", "images": [string, ...]}`. |
| `hitster_safe` | boolean | Whether Hitster-safe mode (music titles hidden) is currently on. |
| `sources` | array | One entry per registered source - see below. |
| `outputs` | array | One entry per registered output type/instance - see below. |
| `enrichers` | array | One entry per registered enricher - see below. |
| `idle_sources` | array | One entry per registered idle wallpaper source, plus any video-output idle sources (pexels/pixabay). |

## Source entries (`sources[]`)

| Field | Type | Notes |
|---|---|---|
| `name` | string | Source plugin name (e.g. `"kodi"`). |
| `status` | string | `"active"`, `"idle"`, `"warning"`, `"error"`, `"disabled"`, or `"not_configured"`. |
| `activity` | string | Machine-readable activity code - see `mediainfo/status.py`. Present for active/configured sources. |
| `activity_label` | string | Human-readable label for `activity`. |
| `last_polled_ago_seconds` | number | Present once the source has been polled at least once. |
| `retry_in_seconds` | number | Present only while backed off after a failure. |
| `failing_for_seconds` | number | Present only while backed off. |
| `last_error` | string | Present only when `status` indicates a problem. |
| *(plugin-specific)* | — | Non-secret scalar config fields (`config_detail_fields()`) and whatever the plugin's own `health_check()` returns are merged in - varies by source type. |

A source not currently active in the orchestrator (disabled, or enabled
but missing from `priority`) still gets an entry with `status: "disabled"`
or `status: "not_configured"`, so every registered source type always
appears exactly once.

## Output entries (`outputs[]`)

| Field | Type | Notes |
|---|---|---|
| `type` | string | Output plugin name (e.g. `"pixoo"`). |
| `status` | string | `"ok"`, `"error"`, `"disabled"`, or `"not_configured"`. |
| `instance_index` | integer | 0-based index among instances of the same type (multi-instance outputs, e.g. two `ulanzi` displays). |
| `last_error` / `last_error_ago_seconds` | string / number | Present only when `status` is `"error"`. |
| `now_playing` | string | `"<source>: <title>"` - present only for an active, non-idle output with per-output source routing in play. |
| *(plugin-specific)* | — | Fields listed in `registries.OUTPUT_DETAIL_FIELDS` for that type, plus whatever the plugin's own `health_check()` returns. |

## Enricher entries (`enrichers[]`)

| Field | Type | Notes |
|---|---|---|
| `name` | string | Enricher plugin name. |
| `status` | string | `"ok"` for an active enricher; `"disabled"` or `"not_configured"` otherwise. |
| *(plugin-specific)* | — | Non-secret config fields plus the enricher's own `health_check()` output. |

## Idle source entries (`idle_sources[]`)

| Field | Type | Notes |
|---|---|---|
| `type` | string | Idle source name. |
| `status` | string | `"ok"`, `"disabled"`, or `"not_configured"`. |
| `wallpapers_loaded` | integer | Present for active idle sources - current batch size. |
| *(plugin-specific)* | — | Whatever the idle source's own `health_check()` returns. |

When more than one idle source is enabled, exactly one supplies any given
batch (see `mediainfo/idle/composite.py`); `wallpapers_loaded` reports the
shared current-batch size under every enabled source's name regardless of
which one actually supplied it.

## Regenerating / verifying this document

There's no generator for this one (unlike `docs/config-reference.md`,
built from the config dataclasses) - the health payload is assembled by
hand in `mediainfo/health.py` from several plugin-family loops, not a
single schema. `tests/test_health.py`'s
`test_health_payload_top_level_shape_matches_the_documented_schema` pins
the top-level key set and `schema_version` value against this document,
so an accidental shape change fails CI instead of silently drifting.
