# 0001. Config UI: two-shell migration, schema-driven forms, and secret/restart semantics

## Status

Accepted. Extracted from `mediainfo/outputs/config_ui.py`'s module
docstring during N6 (see `docs/architecture-usability-review-2026-07.md`);
no behavior changed.

## Context

The config UI (`ConfigUiOutput`, `mediainfo/outputs/config_ui.py`) lets a
non-technical home user configure `mediainfo` without hand-editing YAML,
while still allowing raw YAML edits for anything the guided UI doesn't
cover. It has accumulated several load-bearing but non-obvious design
choices around how the UI is structured, how the form is generated, how
secrets are handled on the wire, and when a restart is actually required.

## Decision

**Two shells, mid-migration.** `/` serves a new Dashboard shell
(`templates/config_ui/dashboard.html`, `static/config_ui/dashboard.{js,css}`)
— a lighter SPA that renders Dashboard/Pipeline itself and otherwise links
into the classic shell for Media/Metadata/Appearance/Displays/Library/
Health/Advanced. The classic shell (`templates/config_ui/app.html`) still
exists unchanged, reachable via `/form` or "Advanced" in the new nav: one
Flask-rendered shell with a sidebar nav and vanilla-JS client-side routing
across nine sections. `library.html`/`overrides.html` remain their own full
pages, linked from the classic shell. Neither shell has a build step —
templates/static files ship as-is. `ui: dashboard` config keeps `/` on the
classic health-grid, for anyone who already set that preference (see
`index()`). See `docs/gui-redesign-phase0-inventory.md` for the phased
migration plan this is partway through.

**The form is generated from config dataclasses.** The guided form is
built from the registered source/output/enricher/idle config dataclasses
(`mediainfo.config.SOURCE_CONFIG_TYPES` etc.) — any config type added there
automatically gets a card, no UI code to update. Only scalar fields
(bool/int/float/str) are editable in the guided UI; list fields
(`transforms`, `blacklist`) are left to the Advanced raw-YAML editor,
except flat lists of strings and the `brightness_schedule`/
`screen_off_hours` time-window fields, which get their own small
structured widgets client-side (see `_field_widget()`).
`_build_schema()` also carries UI-only presentation metadata alongside
each field (friendly label, help text, essential-vs-advanced, required-
for-this-plugin, and a fixed choices list for known enum-like fields) so
the client never needs to know Python dataclass internals to render a
sensible form — this is presentation only; `_scalar_fields()`'s actual
value handling is unchanged from before this metadata existed.

**Outputs support multiple instances; instances are append/remove-from-
the-end only.** Outputs are the only category that supports multiple
instances of the same type (e.g. two `ulanzi` displays), with "+ Add" /
duplicate / remove controls and an optional cosmetic `label` field (see
`_OutputFilterMixin.label` in `mediainfo/config/outputs.py`) so instances
can be told apart by name. Instances can only be appended or removed from
the end — not reordered or removed from the middle — so that non-form
fields like `transforms` on existing instances stay attached to the right
one; saving always overlays posted fields onto the *existing* instance at
each position rather than replacing it outright, so fields on instances
you don't touch survive.

**Every save validates before writing.** Saving always validates the
result with `Config.from_dict()` before writing anything to disk — both
the guided form and the Advanced raw editor go through this same check, so
neither can ever write invalid YAML. The running process's existing
config-file hot-reload (`mediainfo/__main__.py`) picks up the change
within a couple of seconds, no restart needed, **except** for `outputs`,
which are only instantiated once at startup and need a restart to pick up
added/removed/reconfigured instances.

**Secrets never reach the browser in cleartext.** `api_key`, `password`,
`token`, etc. are blanked by `/api/config`, which instead reports whether
one is currently set via a separate `secrets_set` map; the client only
POSTs a secret field back if the user actually typed a new value (see the
"Configured / Replace" UI in `app.html`). Leaving a secret field untouched
in the browser is indistinguishable, on the wire, from never having
included that key at all — and the save path already only overlays
whatever keys are present in the POST body, so an untouched secret is
never overwritten.

**`restart_required` is a coarse flag, not a real diff.**
`self._restart_required` is set whenever a save touches `outputs` (can't
hot-reload) or `auth` (every Flask-based output's HTTP Basic Auth check
closes over the `AuthConfig` instance from process startup — see
`install_auth()` in `SharedHttpServer` — so a changed password doesn't
take effect until the process restarts), and cleared when `/api/restart`
is called; surfaced via `/api/overview` for an Overview-page banner. Any
`outputs`/`auth` save sets it, even a no-op resubmission — deliberately
erring towards nagging rather than missing a real restart-required change.
If locked out and unable to reach this page at all, `python -m mediainfo
set-password` resets `auth.username`/`auth.password` directly in
config.yaml from the command line (same restart caveat applies).

**Restart works via SIGTERM, not a process manager API.** The "Restart"
button sends SIGTERM to this process — the same signal SIGTERM/Ctrl-C/
`docker stop` already trigger, so it shuts down via the existing graceful-
shutdown path. Whether it actually comes back up depends on a process
supervisor: the documented `docker-compose.yml` (`restart: unless-stopped`)
does this automatically; running the process directly with no supervisor
does not.

**Known cosmetic limitation.** When a brand-new instance is appended to an
output type that already has trailing comments after its last existing
instance (e.g. a comment block introducing the next output type),
`ruamel.yaml` can render the new instance's YAML *before* that comment
instead of after it — visually confusing, but the data itself is
unaffected (still parses into the same list, same order). Re-saving via
the Advanced raw editor lets a user tidy the formatting up by hand.

## Consequences

- Adding a new source/output/enricher/idle-provider type gets a working
  guided-UI card for free, as long as its config dataclass only uses
  scalar fields plus the handful of already-supported structured widgets;
  anything else falls through to the raw-YAML editor until a dedicated
  widget is built for it (see `docs/architecture-usability-review-2026-07.md`'s
  M-phase list, and the "Follow-up: outputs.themes has no new-shell
  settings surface" tracked task for a live example).
- The mid-migration two-shell state is deliberate but temporary; H5 in the
  architecture review tracks finishing it into a single nav.
- `restart_required`'s coarseness means a user may occasionally see a
  "restart needed" banner for a resubmission that didn't actually change
  anything — accepted as the safer failure mode over silently missing a
  real one.
- This output has write access to `config.yaml`, including any
  credentials in it, with no authentication of its own beyond whatever
  `SharedHttpServer`'s auth/CSRF/Host-allowlist guards provide — see
  `SECURITY.md` before exposing it beyond a trusted local network.
- The page can also pair an Apple TV (the same pyatv-based flow as
  `python -m mediainfo auth appletv`), without needing shell/docker-exec
  access — see `appletv_pairing.py`'s `AppleTvPairingManager`.
