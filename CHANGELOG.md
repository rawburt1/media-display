# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
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
  config UI output, meant for running a second instance dedicated to "is
  everything working" rather than editing. Shows every source/output/
  enricher as a status card (active, idle, enabled, disabled, error),
  filterable by status, with a per-card "Test connection" button -
  sources are polled once via `get_now_playing()`, enrichers via their own
  internal lookup against a stable real item, outputs via a passive
  TCP/HTTP reachability check that never sends an update to a physical
  display. Has no write access to config.yaml.

### Fixed
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
