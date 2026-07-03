# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Changed
- **Config UI redesign**: the config output's editable form and separate
  read-only dashboard are now one guided single-page app
  (`outputs.config`, still on port 8094 by default) with a sidebar nav
  across nine sections (Overview, Media sources, Displays & outputs,
  Artwork & metadata, Idle screen, Automation & schedules, Library &
  overrides, System status, Advanced configuration), essential-vs-advanced
  field grouping with plain-language help text, source/idle priority
  reordering, per-output content filter and schedule pickers, and a
  sticky save bar. Secrets (API keys, tokens, passwords) are never sent to
  the browser in cleartext - only whether one is configured. See
  [PR #18](https://github.com/rawburt1/media-display/pull/18).

### Fixed
- Docker: the container ran in UTC, so every time-of-day option
  (`active_hours`, `screen_off_hours`, `brightness_schedule`) fired
  offset from wall-clock time. docker-compose.yml now passes `TZ`
  through (set your IANA zone in `.env`, e.g. `TZ=Europe/Stockholm`;
  tzdata is already in the image).

### Added
- **Playback history**: a persistent log of everything that has played
  (SQLite, `history:` config section, on by default), browsable at the
  web output's new `/history` page - grouped by day, with thumbnails
  resolved from the regular artwork cache and a JSON API at
  `/api/history`. One row per genuinely new item; a stop-and-resume of
  the same item within `dedupe_window_seconds` isn't logged twice, an
  item shown by several outputs at once (per-output routing) is logged
  once, and the oldest rows beyond `max_entries` are pruned.
- `outputs.mqtt[].ha_discovery` (default off): publish retained Home
  Assistant MQTT discovery configs on every (re)connect, so a
  "mediainfo" device with two sensors (now-playing state with the full
  payload as attributes, plus a bare title sensor) appears in HA
  automatically - no YAML on the HA side. Includes an availability topic
  with a last-will so the entities show "unavailable" when the process
  is down. The published now-playing payload itself is unchanged.
  `ha_discovery_prefix` covers non-default HA discovery prefixes.
- **Display power/brightness scheduling** for the `pixoo` and `ulanzi`
  outputs: `screen_off_hours: "23:00-07:00"` actually powers the LED
  panel down during the window (unlike `active_hours`, which only
  switches to idle content on a still-lit screen), and
  `brightness_schedule` entries like `"20:00-08:00=15"` dim it on a
  daily schedule (units are device-native: Pixoo 0-100, AWTRIX3 0-255).
  Commands are sent only when the desired state changes, and a failed
  command against an unreachable device retries at most once a minute.
- **Per-output source routing**: each output now shows the
  highest-priority active item its content filters accept, instead of
  every output following one global winner. Two sources playing at once
  (e.g. Kodi in the living room, Sonos in the kitchen) can show on
  different outputs simultaneously - an `allow_media_types: [music]`
  display follows Sonos while an unfiltered one follows Kodi. Outputs
  without filters behave exactly as before. `/health` (and the
  dashboard's output cards) now report which item each output is bound
  to. Behavior changes for existing filter users: an output whose filter
  rejects the playing item now falls through to the next active source
  it accepts (previously it went idle even when one was available), and
  while Hitster-safe suppresses music, a simultaneously-playing
  non-music item (e.g. a movie) can now show instead of everything going
  idle.
- `enrichers.thetvdb.max_search_candidates` (default 5, same as before):
  how many ambiguous title-search results get checked episode-by-episode
  before giving up - now configurable instead of a fixed constant, so it
  can be raised to catch a correct match thetvdb's search ranks further
  down, at the cost of more API calls for generic titles. When no
  candidate can be verified, this now also logs why (which title, how
  many candidates, which episode subtitle) instead of silently adding no
  artwork with no explanation.
- Config validation (see "Fixed" below) now also warns about a source/
  enricher/idle source that's enabled with a required credential left
  blank (e.g. `enrichers.thetvdb` enabled with no `api_key`), and about
  `auth.enabled: true` with a blank username/password - the latter means
  *any* request presenting empty credentials authenticates successfully,
  which is no real protection.
- `outputs.config[].ui: dashboard` (default `form`): a second mode for the
  config UI output - a status overview instead of the full form. Shows
  every source/output/enricher as a status card (active, idle, enabled,
  disabled, error), filterable by status, with a per-card "Test
  connection" button - sources are polled once via `get_now_playing()`,
  enrichers via their own internal lookup against a stable real item,
  outputs via a passive TCP/HTTP reachability check that never sends an
  update to a physical display. Each card also shows its non-secret
  config values (host, port, etc.), and a source currently failing to
  connect shows that error inline next to its badge automatically
  (previously only a bare retry countdown, easy to miss - e.g. the
  `appletv` source gave no visible indication when it couldn't connect).
  A manual "Test connection" result now also survives the dashboard's
  10-second auto-refresh instead of disappearing mid-test. The form and
  dashboard pages (`/form`, `/dashboard`) are both reachable on every
  config UI instance regardless of its `ui` setting, with a nav link
  between them, so one instance gives full access to both instead of
  needing a second instance for the other mode.
- Dashboard cards also have an "Edit" button: turns a card's detail line
  into input fields (reusing the same `/api/schema` and
  `/api/config/form` endpoints the editable form already uses) with
  Save/Cancel, so a source/output/enricher can be reconfigured directly
  from its status card - including enabling/disabling it - without
  switching to the form view. Has the same read/write access to
  config.yaml as the form (not a read-only view).
- Dashboard header now also has a "Restart mediainfo" button (same
  `/api/restart` the form's Restart button already used), so a `ui:
  dashboard` instance doesn't need a trip to `/form` just to restart.
- Manually testing a source via its "Test connection" button now flips
  its badge to a new `unavailable` status (with a matching filter chip)
  when the test fails, instead of leaving it showing `idle` with no
  visible indication. This is independent of the automatic `error`
  status, which only appears once the orchestrator's own background
  polling has actually attempted and backed off that source - a
  lower-priority source can sit at `idle` indefinitely without ever
  being polled while a higher-priority one is active, so a manual test
  is the only way to surface that it's unreachable. The override clears
  on a successful retest, or once the orchestrator reports a concrete
  status (`active` or `error`) for that source on its own.

### Changed
- Since a single config UI instance now reaches both `/form` and
  `/dashboard`, the example/docker-compose setup runs just one (port
  8094 by default) instead of two - drop a second instance you may have
  added on another port (e.g. 8095) and its `docker-compose.yml` port
  mapping unless you specifically want it on a separate port/network
  exposure from the first.

### Fixed
- Dashboard "Edit" input fields used the always-dark `--mono-bg` color
  (meant for the terminal-style test-result box) for their background,
  which made them unreadable (dark text on a dark background) under the
  light theme. They now use the theme-aware `--card` color instead.
- `enrichers.thetvdb`'s title-based series resolution (for sources that
  only know a show's name, not its tvdb id) trusted the first search
  result, which is wrong for common titles matching several unrelated
  shows (e.g. "Kingdom"). When a title search returns more than one
  candidate, each one's actual episode list is now checked against the
  episode subtitle (parsed from `"<number>. <episode title>"`, including
  a Swedish-translation fallback for SVT Play) before trusting it - if
  none can be verified this way, no artwork is added rather than
  attaching a wrong show's poster.
- `WebOutput`'s per-client rotation background thread (`_rotate_clients_loop`)
  had no exception handling: an unexpected error there would silently kill
  the thread and stop per-client rotation for that output forever, with
  nothing logged. It now logs and keeps looping, matching how the
  orchestrator's own main loop already handles this.
- Idle wallpaper (and now-playing image) rotation across multiple outputs
  looked synchronized, for two compounding reasons:
  - Every output's rotation timer started from the exact same instant, so
    they all became "due" to flip to the next image on the same tick
    forever after - now each output's timer starts at a random phase
    within the rotation interval instead, so they drift apart and rotate
    independently.
  - Each output picked its starting picture from its own independently
    shuffled order, which (especially with a modest-sized image pool) could
    coincidentally collide and show the same picture as another output -
    outputs now share one shuffled order but start at different positions
    in it, so as long as there are at least as many images as outputs, no
    two outputs ever show the same picture at the same time.
  - Both of the above only desynchronize separate *outputs* - multiple
    screens/browsers all pointed at the same `web` output's port were
    still all seeing one identical broadcast, since that's a single
    output instance from the orchestrator's point of view no matter how
    many clients connect to it. Each WebSocket connection to the `web`
    output now gets its own independent rotation (own shuffled order,
    own staggered timer) the same way separate outputs do, so multiple
    screens can share one port and still show different pictures. The
    `/image/current` endpoint now takes a `v=<id>` param identifying which
    cached image to serve (previously always the single most-recently-set
    one, with `v` only used for browser cache-busting) so each client's
    chosen image is actually distinct, not just labeled differently.

### Added
- The Shield source now reports apps known to stream TV/video (currently
  SVT Play - see `_VIDEO_PACKAGES` in `sources/shield.py`) as `episode`
  instead of `music`, and `enrichers.thetvdb` can now resolve a series by
  title (cached in memory, written back into `now_playing.ids` so
  `enrichers.fanarttv`'s TV branch can use it too) - previously these
  sessions were always reported as music, so neither artwork enricher
  ever ran for them, no matter the title. Reordered `enrichers.thetvdb`
  before `enrichers.fanarttv` in config.example.yaml so the resolved id
  is available to both.
- Startup (and config-reload) validation warns when a source is `enabled:
  true` but missing from `priority` - previously this failed completely
  silently (the source is just never instantiated, see `_build_sources()`),
  which is exactly what happened to this deployment's own `spotify` source.
- New optional `auth` config section (off by default): HTTP Basic Auth
  for the web/config/info/feed/video/nest_hub outputs. Requests from
  RFC1918 private-use addresses and loopback are never challenged
  regardless of `enabled`, so a typical LAN-only setup is unaffected -
  this is meant for exposing one of these outputs beyond your LAN
  (port-forwarding, a reverse proxy, a VPN you don't fully trust, ...)
  without requiring every device on your own network to log in.
- Music library artist/album/track matching is now fuzzy-tolerant: case,
  accents, "&" vs "and", and punctuation differences no longer cause a
  miss (e.g. a source reporting "Simon and Garfunkel" now matches a
  library entry imported as "Simon & Garfunkel"). Existing databases are
  migrated automatically (a one-time backfill) on next startup.
- New `idle.library` idle wallpaper source: shows cover art from random
  albums in the local music library while nothing is playing, no API key
  required (only the free Cover Art Archive for the actual images,
  cached per album to avoid repeat lookups).
- New library browser at `/library` on the `config` output - search
  artists and see their albums/tracks/MusicBrainz ids, useful for
  checking what's actually in the local library and debugging match
  misses.
- New `enrichers.library` enricher: for sources that don't report an
  album at all (e.g. YouTube), looks up the playing artist+song in the
  local music library and adds cover art for every album the song
  appears on - a song on multiple releases gets art for all of them, not
  just the first match. Backed by a new `track_albums` table in the
  music library, populated by `import-lidarr` (which now also imports
  each track's album linkage, not just its own mbid).
- `python -m mediainfo import-lidarr --url <lidarr-url> --api-key <key>`
  bulk-imports a [Lidarr](https://lidarr.audio/) library's already-verified
  artist/album/track MusicBrainz ids into the local music library cache
  (see below), so enrichers have everything cached up front instead of
  discovering it one play at a time.
- Local SQLite metadata cache (`library.db_path`, new `mediainfo.musiclibrary`
  module) of artist/album/track ids and "claims" (cover art URLs, artist
  photos), queried by the musicbrainz, fanarttv, discogs, and lastfm
  enrichers before they make an external API call. Previously
  musicbrainz.py and fanarttv.py each independently re-resolved the same
  artist+album to MusicBrainz ids on every play, and nothing persisted
  across restarts; now the resolution (and each enricher's own
  artwork/photo result, including a cached "nothing found") happens once
  per artist/album/song and is reused from then on. MusicBrainz is
  treated as the source of truth for canonical ids.
- `logging.level` config option (`DEBUG`/`INFO`/`WARNING`/`ERROR`/
  `CRITICAL`, default `INFO`) to control verbosity without code changes -
  switch to `DEBUG` to see things like every Sonos coordinator
  checked/skipped, normally too noisy for everyday use.
- `sources.sonos.speaker_ip` is now `speaker_ips` (a list). Previously the
  Sonos source discovered the whole household's zone topology from a
  single configured speaker, so if that one speaker was off or
  unreachable, every other zone became invisible too even though any
  speaker can report the full topology. Now it tries each configured
  speaker in turn until one answers, so listing more than one (e.g. one
  per room) keeps every zone visible.
- Sources whose device/service can't be reached are now backed off by the
  orchestrator instead of being polled every tick forever: 30s after the
  first consecutive failure, doubling up to a 5-minute cap, resetting the
  moment a poll succeeds again. Sources report this via a new
  `last_poll_failed` flag (set when `get_now_playing()` returns `None`
  because of a connection error, left `False` when it connected fine and
  simply found nothing playing) - added to all 9 sources. Backed-off
  sources show up in `/health` as `status: "error"` with a
  `retry_in_seconds` field.
- `sources.youtube` now splits video titles that look like
  "`Song` - `Artist`" (song first), using the title's artist instead of
  the channel name - unless the part after the dash is a version/edition
  tag like "Live" or "Remix" (a fixed keyword list), which is treated as
  decoration instead. All parenthesized/bracketed text (e.g.
  "(Official Video)", "[Remastered 2011]", "(feat. Someone)") is now
  stripped from the title too, not just the previous fixed set of
  "Official Video/Audio/Lyrics" suffixes. A dash glued directly onto a
  word with no space before it (e.g. "Led Zeppelin- The Battle of
  Evermore", a stray punctuation artifact in some real-world titles) is
  now removed outright, rather than being mistaken for a "<Song> -
  <Artist>" separator.
- The `config` output's `appletv` source card now has a "Pair" button
  driving the same pyatv-based pairing flow as
  `python -m mediainfo auth appletv` (scan, begin pairing, enter/confirm
  a PIN, finish) entirely from the browser, saving the resulting
  `companion_credentials`/`mrp_credentials` directly to config.yaml - no
  shell/docker-exec access needed. Verified end-to-end in a real browser
  with mocked pyatv calls. Pairing is async and gets its own short-lived
  background event loop thread per attempt (`/api/appletv/pair/start`,
  `/finish`, `/cancel`); only one attempt is tracked at a time.

### Fixed
- `python -m mediainfo auth appletv` was broken: this pyatv version
  requires an explicit `loop` argument to `pyatv.scan()`/`pyatv.pair()`
  that wasn't being passed, so it always raised `TypeError`. Found and
  fixed while building the web-based pairing flow above.
- `sources.appletv`'s actual runtime connection (`AppleTvSource._connect`)
  had the same missing-`loop` bug in `pyatv.scan()`/`pyatv.connect()` -
  found by testing pairing against a real device, where pairing itself
  succeeded but the source then failed to connect on every poll. Fixed
  by passing the source's own background event loop, which it already
  maintains for running coroutines via `run_coroutine_threadsafe`.
- `docker-compose.yml` now bind-mounts `./config` as a directory
  (containing `config.yaml`) instead of bind-mounting `config.yaml`
  itself. A single-file bind mount pins to that file's inode; any tool
  that saves by replacing the file (atomic rename, rather than writing in
  place) orphans the mount, so the running container keeps serving the
  old content until the container is recreated (a restart isn't enough -
  this bit the new `config` output's Restart button, and separately any
  direct edits to config.yaml). Existing setups need to move their
  config.yaml into `./config/config.yaml` and update any
  `docker compose run` commands to add `--config config/config.yaml`.
- `ImageCache` now sends a descriptive `User-Agent` header when downloading
  artwork. Wikimedia (used by the Wikipedia enricher's thumbnails) rejects
  the default python-requests User-Agent with a 403, so those photos were
  silently failing to download.

### Added
- The `config` output now has a "Restart" button (`POST /api/restart`),
  since `outputs` changes (added/removed/reconfigured instances) only take
  effect after a restart - unlike sources/enrichers/idle sources, which
  pick up changes via the existing hot-reload. It sends SIGTERM to the
  process, reusing the existing graceful-shutdown path; whether it comes
  back up depends on a process supervisor (Docker's
  `restart: unless-stopped`, already configured, handles this).
- The `config` output's web form now supports multiple instances of
  multi-instance-capable outputs (e.g. two `ulanzi` displays), with
  "+ Add instance" / "- Remove last" controls per output type. Previously
  only the first instance of any list-configured output was editable in
  the form. Instances can only be appended/removed from the end (not
  reordered) so non-form fields like `transforms` stay attached to the
  right instance when saving.
- `mediainfo/sources/youtube.py`: `sources.youtube` source for the YouTube
  app on Android TV (e.g. Nvidia Shield), via ADB. Unlike the generic
  `shield` source, this targets YouTube specifically, reporting the video
  title and channel name (treated as the artist) as music - the existing
  music enrichers (fanart.tv/MusicBrainz/Last.fm/Discogs/Wikipedia) take
  over for artwork/bio info. An earlier version of this tried to filter to
  only videos that "look like" songs (a "`Artist` - Topic" channel
  convention, or "`Artist` - `Song`" in the title), but real-device
  testing showed YouTube TV's media session doesn't expose anything that
  reliably distinguishes a song from any other video, so that filtering
  was dropped before release.
- Wikipedia enricher lookups (search + summary) are now cached in memory
  for the life of the process, keyed by artist/movie/show. The orchestrator
  already skips re-enriching the same continuously-playing item, but
  replaying the same content across separate sessions previously hit
  Wikipedia's API every time; "nothing found" results are cached too, to
  skip wasted retries.
- Idle wallpapers (Unsplash, Last.fm scrobble history) are now cached under
  a separate `<cache.dir>/idle` subdirectory with their own, much shorter
  retention window - `cache.idle_max_age_hours` (default 48) instead of
  `cache.max_age_days` (default 30 days) - since they're decorative and
  easily refetched rather than tied to a specific now-playing item.
- `mediainfo/idle/lastfm.py`: `idle.lastfm` wallpaper source - shows album
  art from a configured Last.fm user's recent scrobbles on outputs while
  nothing is playing, deduplicated by album art URL. Free API key, same
  one used by `enrichers.lastfm` if that's also enabled.
- `mediainfo/enrichers/wikipedia.py`: Wikipedia enricher adding an artist
  bio / movie info / TV show info summary (`NowPlaying.summary`) plus a
  thumbnail photo, via the free public Wikipedia REST API (no API key).
  Falls back to "(band)"/"(musician)" disambiguators when the plain
  artist name resolves to a disambiguation page instead of the artist
  (e.g. "Queen" -> "Queen (band)").
- `mediainfo/outputs/info.py`: high-resolution `info` output (default port
  8093) pairing the current artwork with its Wikipedia summary text. No
  image transforms are applied by default, so artwork is shown at its
  original resolution.
- Feed output (`outputs.feed`, RSS/Atom) now includes the Wikipedia summary
  in each entry's description when one was found.
- `mediainfo/outputs/config_ui.py`: `config` output (default port 8094) - a
  web page for editing every config option (sources, outputs, enrichers,
  idle sources, polling intervals), auto-generated from their config
  dataclasses, plus an "Advanced" raw-YAML editor for list-typed fields.
  Saves are validated with the new `Config.from_dict()` before being
  written, and round-trip through `ruamel.yaml` to preserve existing
  comments in config.yaml. Picked up by the existing config hot-reload -
  no restart needed. Has write access to config.yaml including any
  credentials in it and no authentication of its own; see SECURITY.md.
- `Config.from_dict()`: builds a `Config` from an already-parsed dict,
  split out of `Config.load()` so the new `config` output can validate
  edits before writing them to disk.
- `mediainfo/sources/jellyfin.py`: Jellyfin and Emby sources (Sessions API).
- `mediainfo/enrichers/discogs.py`: Discogs enricher for album cover art.
- `/health` endpoint on the web output reporting uptime, current
  now-playing item, and per-source/output/enricher status.
- GitHub Actions workflow running the test suite on every push/PR, with a
  required status check on `master`.
- CONTRIBUTING.md, CODE_OF_CONDUCT.md, LICENSE (MIT), and CI/license status
  badges.
- CHANGELOG.md, CODEOWNERS, SECURITY.md, and GitHub pull request/issue
  templates.
- `.editorconfig`.
- Branch protection on `master`: requires the `test` CI check to pass and
  1 approving PR review before merging (repo admins are exempt).

### Changed
- CODE_OF_CONDUCT.md now uses the exact Contributor Covenant v2.0 text
  (only the enforcement contact line is customized), so GitHub's
  community-profile detector recognizes it as Contributor Covenant
  instead of "Other".

### Notes
- Going forward, CHANGELOG.md updates accompanying a change are folded
  into that change's own entry rather than logged separately.

### Changed
- Renamed the `pixoo_media` package to `mediainfo` (Dockerfile,
  docker-compose.yml, config.example.yaml, vinyl_recognizer references)
  to reflect that the app now drives many more outputs than just a Pixoo64.

## [0.4.0]
### Added
- Spotify source (Web API), with an `auth spotify` CLI flow for OAuth.
- MusicBrainz Cover Art Archive enricher.

### Fixed
- Sonos source no longer skips all zones when one coordinator is unsupported.
- Sonos source now detects playback during the `TRANSITIONING` state.

## [0.3.0]
### Added
- Apple TV source (Companion/MRP/AirPlay via pyatv), with an `auth appletv`
  CLI pairing flow.
- Plex source.
- Android TV / Nvidia Shield source (via ADB).
- Vinyl turntable source, backed by a companion `vinyl_recognizer` service
  (audio recognition via AudD).
- MQTT publish output.
- RSS/Atom feed output.
- Folder export output.
- Google Nest Hub (Cast) output.
- Ulanzi TC001 (AWTRIX3) scrolling-text output.
- Last.fm artist-photo enricher.
- TheTVDB episode-art enricher.
- Per-output image transform pipeline (fit, pad, resize, blur, contrast, etc).
- WebSocket push in the web output, replacing polling.
- Graceful SIGTERM/SIGINT shutdown with `on_idle()` cleanup.
- Config hot-reload: changes to `config.yaml` take effect without a restart.
- Pixoo64 LED image quality improvements (contrast boost, unsharp mask,
  LANCZOS downscale, 24-colour palette quantisation, optional 512x512
  preview PNG).

### Changed
- Improved `config.example.yaml` with full descriptions and list syntax
  examples.

## [0.2.0]
### Added
- Video output: ambient Pexels/Pixabay videos while idle, switching to
  artwork while something plays.
- Idle wallpaper support via Unsplash.

## [0.1.0]
### Added
- Initial release: Kodi and Sonos sources, fanart.tv enricher, Pixoo64 and
  local web page outputs, disk cache for downloaded artwork.
