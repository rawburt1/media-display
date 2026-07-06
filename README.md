# mediainfo

[![Tests](https://github.com/rawburt1/media-display/actions/workflows/tests.yml/badge.svg)](https://github.com/rawburt1/media-display/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Polls "now playing" media sources on your network and shows the current
album art / poster on a [Divoom Pixoo64](https://divoom.com/) LED display,
a Ulanzi TC001, a Google Nest Hub, a simple local web page, and more.

## Status

Currently implemented:

- **Sources**: Kodi (movie/episode posters+fanart, music), Plex (movie/episode
  posters+fanart, music), Jellyfin and Emby (movie/episode posters+fanart,
  music, via the Sessions API), Sonos (album art), Spotify (current playback
  via the Web API), Mopidy (music, via its core JSON-RPC API - backend-
  agnostic, works the same regardless of which Mopidy backend is actually
  playing), MPD/Music Player Daemon (music, including embedded/folder
  cover art when the server supports it), Logitech Media Server/Squeezebox
  (music, auto-selects the active player across a multi-player household
  unless `player_id` is set), Apple TV (any app, via the Companion/MRP/AirPlay
  protocols), **the YouTube *app* on Android TV** (⚠️ not YouTube in
  general - this works only via ADB against an actual Android TV device
  running the YouTube app, e.g. an Nvidia Shield; it cannot see YouTube
  played in a browser, on a phone, on a smart TV's own built-in app, or
  anywhere else - reports a song only when the video looks like one, see
  "Extending" below), Android TV / Nvidia Shield (via ADB, generic "now
  playing" from any other app on the same device), vinyl turntable
  (audio recognition via [vinyl_recognizer](vinyl_recognizer/) + AudD),
  Home Assistant (polls a single media_player entity via HA's REST API -
  a fallback for devices a more specific source can't read directly, e.g.
  a tvOS app that doesn't populate Apple's own now-playing API), generic
  Chromecast/Cast (polls any configured Cast device's media status
  directly, so anything cast to it - Netflix, Disney+, YouTube, Spotify
  Connect, etc. - is picked up regardless of which app is casting, unlike
  the Shield source which only sees apps running locally on that device)
- **Enrichers**: fanart.tv and thetvdb.com add extra posters/fanart for
  movies and TV shows (matched via tmdb/imdb/tvdb ids); fanart.tv and
  Discogs also add (and prefer) album covers for music, matched via
  MusicBrainz ids or, failing that, by looking up the artist/album name
  (e.g. for Sonos) via the MusicBrainz API or Discogs' search; Last.fm adds
  artist photos; Wikipedia adds an artist bio / movie info / TV show info
  summary plus a photo, for the `info` output and RSS/Atom feeds below;
  Sonarr/Radarr/Lidarr each match against your own library (rather than a
  public catalog) and add a studio/genres/discography plus poster/fanart/
  album art - see below; TMDb and
  OMDb each add a 0-10 rating for movies/TV shows, also for the `info`
  output - both can be enabled at once without conflict, since neither
  overwrites a rating the other already found
- **Outputs**: Pixoo64 (local HTTP API), web page (`http://<host>:8090/`),
  and Google Nest Hub (Cast) each rotate between all available poster/fanart
  images for the current item on their own randomized schedule - each one
  picks its own shuffled order, so they don't all show the same image at
  the same time; folder export mirrors all of the current item's artwork to
  a local directory; Ulanzi TC001 (AWTRIX3) shows the current item as
  scrolling text instead of artwork (e.g. "Artist - Song",
  "Title (Year)", "Show s01e01"); video output serves a full-screen web
  player that shows idle stock-footage clips (Pexels/Pixabay) and switches
  to artwork when something plays; info output (`http://<host>:8093/`)
  pairs the current artwork at its original (high) resolution with the
  Wikipedia summary text; MQTT publishes now-playing state to a broker topic;
  feed output serves RSS/Atom feeds describing only the currently playing
  item, including the Wikipedia summary when available; config output
  (`http://<host>:8094/`) is a web page for editing every config option
  above (sources, outputs, enrichers, idle sources, polling intervals,
  including most list-valued fields like Sonos speaker IPs) without
  hand-editing YAML - saved changes are hot-reloaded within a few seconds,
  and it has a "Hitster-safe" button that suppresses song/artist/album
  display across *every* output (falling back to idle wallpapers/text
  instead) while it's on, so a song's title/artist never leaks onto a
  screen mid-round of Hitster or similar music-guessing games
- **Idle wallpapers**: Unsplash, Pexels, local folders (random pictures
  from your own collection - see `idle.local` below), Last.fm scrobble
  history (album art from your recent scrobbles), and/or your own music
  library (random covers from imported albums) - while nothing is
  playing, downloads/picks a fresh batch of wallpapers every
  `rotation_interval_seconds`, and each output independently rotates
  through that batch on its own randomized schedule (same as the
  now-playing artwork rotation above). Multiple idle sources can be
  enabled at once, each refetched independently on its own schedule, but
  they're never mixed within a single batch - `idle_priority` (an ordered
  list of source names) picks which one supplies any given batch: the
  first one in that list with wallpapers available wins, so e.g. enabling
  both Unsplash and Pexels means one being temporarily unreachable falls
  through to the other instead of blanking outputs. `idle_mode: random`
  (instead of the default `priority`) picks the winning source at random
  each batch instead of always preferring the same one first - either
  way, exactly one source's pictures show per batch, never blended. The
  last successfully-fetched batch is also persisted to disk and reloaded
  on restart, so a source being down right when the process restarts
  doesn't blank outputs either, as long as the previous batch's cached
  image files haven't since been purged (see `cache.idle_max_age_hours`).
- **Manual artwork overrides**: pin a specific image for a title/subtitle
  that never gets a good poster from any enricher, via the config UI's
  "Overrides" page - on by default (`overrides.enabled: true`)
- **Alerting**: optionally POST a webhook (Slack, Discord, ntfy.sh,
  healthchecks.io, or any endpoint that accepts JSON) once an output has
  been continuously failing for a while (e.g. a Pixoo64 that's gone
  unreachable on the network) - off by default, see `alerts` below
- Disk cache for downloaded artwork (each image is only fetched once,
  and unused files are purged after `cache.max_age_days`)
- `/health` endpoint (on the web output) reports uptime, the current
  now-playing item, and per-source/output/enricher status - JSON by default,
  or an HTML dashboard when requested with `Accept: text/html`

In progress, not yet active (nothing in the running app reads these yet):

- **`mediadata`**: a unified, human-browsable on-disk cache
  (`mediainfo/media_data_store.py`) organizing artwork/lyrics/metadata as
  `movies/<Title> (<Year>)/poster.jpg`, `music/<Artist>/<Album> (<Year>)/
  albumart.jpg`, etc., each with a `metadata.json` recording where each
  file came from and when it was last checked/refreshed - a cache-first
  design with a per-media-type refresh policy (`mediadata.refresh`, see
  config.example.yaml), instead of today's flat `cache/` directory. The
  external-fetch step is currently a stub (no real API calls yet); this
  is groundwork for a future artwork/lyrics cache redesign, not a
  replacement for the existing cache yet.

## Setup

### Requirements

- **Docker + Docker Compose** (recommended - no Python setup needed), **or**
  Python 3.10+ if you'd rather run it directly on the host.
- At least one supported media source reachable on your network (see
  "Sources" above) and its IP/credentials. You don't need all of them - one
  source and one output is enough to get something on screen; add more
  later by re-editing config.yaml - most changes hot-reload within a few
  seconds (see "Configuration" below for the exceptions).

### Getting API keys (only fill in what you actually use)

Nothing below is required to get *something* on screen - Kodi, Plex,
Sonos, Jellyfin/Emby, Apple TV, Home Assistant, Shield/YouTube (ADB), and
Chromecast all need no API key at all, just a host/IP on your network.
The free services below add extra artwork/metadata/wallpapers and are
entirely optional - skip any row for a feature you don't care about.

| For | Get a key/token at | Used by |
|---|---|---|
| Plex | [Find your X-Plex-Token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/) | `sources.plex` |
| Jellyfin | Dashboard → Advanced → API Keys → New API Key | `sources.jellyfin` |
| Emby | the equivalent Emby settings page | `sources.emby` |
| Spotify | [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) (free app) | `sources.spotify` |
| Vinyl recognition | [AudD](https://audd.io/) - see [vinyl_recognizer/README.md](vinyl_recognizer/) | `sources.vinyl` |
| fanart.tv | [fanart.tv/get-an-api-key](https://fanart.tv/get-an-api-key/) | `enrichers.fanarttv` |
| TheTVDB | [thetvdb.com/dashboard/account/apikey](https://thetvdb.com/dashboard/account/apikey) | `enrichers.thetvdb` |
| Sonarr | Settings → General → Security | `enrichers.sonarr` |
| Radarr | Settings → General → Security | `enrichers.radarr` |
| Lidarr | Settings → General → Security | `enrichers.lidarr` |
| Discogs | [discogs.com/settings/developers](https://www.discogs.com/settings/developers) | `enrichers.discogs` |
| Last.fm | [last.fm/api/account/create](https://www.last.fm/api/account/create) | `enrichers.lastfm` and `idle.lastfm` (same key works for both) |
| TMDb | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) | `enrichers.tmdb` |
| OMDb | [omdbapi.com/apikey.aspx](https://www.omdbapi.com/apikey.aspx) | `enrichers.omdb` |
| Unsplash | [unsplash.com/oauth/applications](https://unsplash.com/oauth/applications) | `idle.unsplash` |
| Pexels (video clips and/or idle wallpapers) | [pexels.com/api](https://www.pexels.com/api/) | `outputs.video`, `idle.pexels` (same key works for both) |
| Pixabay (video output) | [pixabay.com/api/docs](https://pixabay.com/api/docs/) | `outputs.video` |

No key needed: Wikipedia, MusicBrainz (bio enrichers), and the
Kodi/Plex/Sonos/Jellyfin-Emby/Shield-YouTube/
Chromecast/Home Assistant sources (host+credentials on your own network
instead). Apple TV doesn't use an API key either - it's a one-time
on-device pairing flow instead, see `sources.appletv` further down.

### Quick start (Docker - recommended)

```bash
git clone https://github.com/rawburt1/media-display.git
cd media-display

./setup.sh                     # creates config/, cache/, etc. and config/config.yaml
nano config/config.yaml        # fill in your devices' IPs/credentials

docker compose up -d
```

`./setup.sh` creates every directory `docker-compose.yml` bind-mounts
(`config/`, `cache/`, `library/`, `logs/`, `adb_keys/`, `artwork/`,
`spotify_cache/`, `overrides/`) and copies `config.example.yaml` to `config/config.yaml`
if it isn't there yet. Running it yourself first matters: Docker otherwise
creates any missing mount target itself as root, which the container's
non-root app user can't then write into. config.yaml lives in
`./config/config.yaml` rather than the project root because it's
bind-mounted as a directory, so editors/tools that save by replacing the
file (rather than writing in place) don't orphan the mount.

Open `http://<this-machine>:8090/` - if you enabled at least one source and
output in config.yaml, you should see either its artwork or an idle
wallpaper within a few seconds. Check `docker compose logs -f` if not (see
"Troubleshooting" below).

To update later: `git pull && docker compose up -d --build`.

### Manual install (no Docker)

```bash
git clone https://github.com/rawburt1/media-display.git
cd media-display

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml
nano config.yaml               # fill in your devices' IPs/credentials

python -m mediainfo --config config.yaml
```

The web page is then available at `http://<this-machine>:8090/`.

To update later: `git pull && pip install -r requirements.txt`.

### Troubleshooting

- **Nothing shows up / `/health` reports sources as `not_configured`**: a
  source needs both `enabled: true` *and* to be listed in the top-level
  `priority:` list in config.yaml - being enabled isn't enough on its own.
- **Container restarts in a loop**: `docker compose logs` will show a
  traceback from `Config.load()` if config.yaml has a YAML syntax error or
  a field of the wrong type - compare against config.example.yaml.
- **A source connects but never shows artwork**: check `/health` (e.g.
  `http://<this-machine>:8090/health`, or with `Accept: text/html` in a
  browser for a dashboard view) - it reports each source/output/enricher's
  live status, including the last error for anything that's failing.
- **Spotify/Apple TV need a one-time interactive login**: see their entries
  under "Configuration" below (`python -m mediainfo auth spotify` /
  `auth appletv`) - run via `docker compose run --rm mediainfo python -m
  mediainfo auth spotify --config config/config.yaml` if using Docker.
- **Forgot the config UI password / locked out**: `python -m mediainfo
  set-password --config config.yaml` resets it from the command line - see
  "Resetting the config UI password" under `auth` in Configuration below.
- **A save left config.yaml broken/wrong**: every save (from the config UI,
  or `set-password`) copies the previous config.yaml into a `.config_backups/`
  folder right next to it before writing - e.g.
  `config/.config_backups/config.yaml.20260704T101530.bak`. Restore one with:
  ```bash
  python -m mediainfo restore-backup --config config.yaml
  # or, running under Docker:
  docker compose run --rm mediainfo python -m mediainfo restore-backup --config config/config.yaml
  ```
  With no `--backup`, it lists the available backups (newest first) and
  prompts for which one to restore; pass `--backup latest` (or a filename
  from `--list`) plus `--yes` to script it non-interactively. The config.yaml
  being replaced is itself backed up first, so a restore can always be
  undone the same way. The last 10 backups are kept; older ones are pruned
  automatically. Restart afterwards if the restored config changes
  `outputs` or `auth` - everything else hot-reloads within a few seconds.
  No shell access? The config UI's "Advanced configuration" page has the
  same list under a "Backups" panel, with a Restore button per entry.

## Configuration

See `config.example.yaml` for all options. Key things to fill in:

- **`priority`**: ordered list of source names. When more than one source
  is active at once, the first one in this list wins. A source that's
  `enabled: true` but missing from this list is never actually polled -
  logged as a warning at startup and on every config reload, so this
  mistake doesn't fail silently. The same startup/reload check also warns
  about a source/enricher/idle source that's enabled with a required
  credential left blank (e.g. `enrichers.thetvdb` with no `api_key`), and
  about `auth.enabled: true` with a blank username/password (see `auth`
  below).
- **`idle_priority`** / **`idle_mode`**: the `priority` list above, but for
  idle wallpaper sources (`idle.unsplash`, `idle.pexels`, `idle.local`,
  ...) - unlike regular sources, multiple idle sources being enabled at
  once is normal and expected, but they're never mixed within one batch.
  `idle_priority` is an ordered list of idle source names; the first one
  in it with wallpapers available supplies the whole batch (any enabled
  source not listed is tried last, in its `idle:` config order). Leave it
  empty (the default) to just use `idle:`'s own order. `idle_mode: random`
  (default `priority`) picks the winning source at random each batch
  instead of always preferring the same highest-priority one first - either
  way, exactly one source's pictures show per batch, never blended.
- **`sources.kodi`**: Kodi host/port and credentials. In Kodi, enable
  *Settings → Services → Control → Allow remote control via HTTP*.
- **`sources.sonos`**: IP address of every Sonos speaker on your network
  (find them in the Sonos app under speaker settings, or your router's
  device list). Any one of them can report the full household topology,
  so listing more than one keeps every zone visible even if a particular
  speaker is temporarily off or unreachable.
- **`sources.plex`**: host/port of your Plex Media Server and an
  [X-Plex-Token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).
- **`sources.jellyfin`** / **`sources.emby`**: host/port and an `api_key`
  generated from *Dashboard → Advanced → API Keys → New API Key* (Jellyfin)
  or the equivalent Emby settings page.
- **`sources.spotify`**: `client_id`/`client_secret` from a free app at
  https://developer.spotify.com/dashboard, with
  `http://localhost:8888/callback` (or your configured `redirect_uri`) added
  as a Redirect URI. Authorize once with
  `python -m mediainfo auth spotify --config config.yaml` (or
  `docker compose run --rm mediainfo python -m mediainfo auth spotify
  --config config/config.yaml`), which opens a login flow and caches the
  token at `cache_path`. Only reports playback on the account that's
  actively listening.
- **`sources.appletv`**: `host` is the Apple TV's IP/hostname. Pair once
  with `python -m mediainfo auth appletv --config config.yaml` (or the
  `docker compose run` equivalent, with `--config config/config.yaml`)
  - follow the prompts to enter the PIN
  shown on the TV, then paste the printed credentials into config.yaml -
  or, easier, use the "Pair" button on the `appletv` card of the
  `config` output's web page (see below), which drives the same flow
  and saves the credentials for you, no shell/docker-exec access needed.
  Reports whatever's playing in any app (TV+, Plex, Infuse, music apps,
  etc.) via the Companion/MRP/AirPlay protocols. Limitation: this only
  works for apps that populate Apple's own now-playing API - some
  third-party tvOS apps (SVT Play, notably) never do, so pyatv can only
  ever see the device as idle while they're actually playing something.
  `sources.homeassistant` below is a workaround for exactly that case.
- **`sources.homeassistant`**: polls a single `media_player` entity via
  Home Assistant's REST API - `host`/`port`/`use_ssl` point at HA itself,
  `token` is a long-lived access token (HA UI: your profile → Security →
  Long-lived access tokens → Create Token), and `entity_id` is the entity
  to read (HA UI: Settings → Devices & Services → Entities). Not specific
  to Apple TV - this works for any device HA tracks - but its main use is
  as a fallback for `sources.appletv`: list it right after `appletv` in
  `priority` so it only gets polled once appletv has confirmed pyatv
  itself sees nothing playing, for an app like SVT Play that HA's own
  Apple TV integration can apparently still see (likely via an MRP
  pairing made back when the device still advertised that protocol -
  pairing fresh today only offers Companion/AirPlay, which expose far
  less now-playing metadata to third-party clients).
- **`sources.shield`**: IP address of an Android TV device (e.g. Nvidia
  Shield) - can be the same device as `sources.kodi`, since this reads the
  Android-level "now playing" media session (Spotify, YouTube Music, SVT
  Play, etc.) rather than Kodi specifically. Requires ADB debugging enabled
  on the device (*Settings -> Device Preferences -> About -> click "Build"
  7 times to enable Developer options, then Developer options -> enable
  "USB debugging" and "Network debugging"*). On first run, an ADB key pair
  is generated under `adb_key_path` and the device will show an "Allow USB
  debugging?" prompt - accept it (and tick "Always allow") so future
  connections don't need re-approval. No artwork is available this way; for
  music apps, fanart.tv's MusicBrainz lookup (see below) is used instead.
  Apps known to stream TV/video rather than music (currently just SVT
  Play - see `_VIDEO_PACKAGES` in `sources/shield.py`, easy to extend) are
  reported as `episode` instead of `music`, so `enrichers.thetvdb` can
  resolve the show by title and add a poster.
- **`sources.youtube`**: ⚠️ despite the name, this is **not** "now playing
  on YouTube" in general - it only ever sees the YouTube *app* running on
  an Android TV device (e.g. an Nvidia Shield) that this machine has ADB
  access to. It cannot detect YouTube played in a desktop/mobile browser,
  a phone app, a smart TV's own built-in YouTube app, or anything not
  running on the specific Android TV box you point `host` at. Same
  `host`/`port`/ADB pairing flow as `sources.shield` above (can point at
  the same device - use a separate `adb_key_path`), but targets the
  YouTube app specifically rather than whatever app is in the foreground,
  reporting the video title and channel
  name (treated as the artist) as music. YouTube TV's media session
  doesn't expose anything that reliably distinguishes a song from any
  other video (a music track and a vlog report the exact same fields), so
  this reports whatever's actively playing rather than trying to filter -
  the usual music enrichers (fanart.tv/MusicBrainz/Last.fm/Discogs/
  Wikipedia) simply won't find anything to add for a channel name that
  isn't a real artist. If the video title itself looks like
  "`Song` - `Artist`" (song first), that's split and used instead of the
  channel name - unless the part after the dash is a version/edition tag
  like "Live" or "Remix", which is just stripped as decoration. All
  parenthesized/bracketed text (e.g. "(Official Video)", "[Remastered
  2011]") is stripped from the title too. Put `youtube` ahead of `shield`
  in `priority` so it takes precedence when both point at the same device.
- **`sources.vinyl`**: host/port of a [vinyl_recognizer](vinyl_recognizer/)
  instance - a separate service that runs on the machine a Behringer UCA202
  (or similar USB audio interface) is connected to, listens to a turntable's
  output, and identifies the playing track via [AudD](https://audd.io/). See
  `vinyl_recognizer/README.md` for setup.
- Any entry under `outputs` can be a single config (as below) or a list of
  configs, to run multiple instances of that output at once - e.g. several
  Ulanzi displays in different rooms, or web servers on different ports. If
  you add multiple `web` or `nest_hub` instances, make sure each one uses a
  distinct `port`/`server_port` and update `docker-compose.yml` accordingly.
- **`outputs.config`**: `host`/`port` (default 8094) for a guided web app
  that configures mediainfo without needing to know YAML - a single-page
  shell (sidebar nav on desktop, a hamburger menu on narrow screens) with
  nine sections: Overview, Media sources, Displays & outputs, Artwork &
  metadata, Idle screen, Automation & schedules, Library & overrides,
  System status, and Advanced configuration. It's generated automatically
  from the source/output/enricher/idle config dataclasses, so a new plugin
  type gets a card with no UI code to write - only a friendly label/
  description/help text needs adding (see `_TYPE_INFO`/`_FIELD_HELP` in
  `mediainfo/outputs/config_ui.py`) for it to read well, and it still works
  without those.
  - **Overview** is the everyday home page: current health, what's
    playing, enabled-item counts, and a "needs attention" list (an enabled
    source missing from priority, a plugin missing a required setting, an
    unreachable source/output, outputs changed but not yet restarted, or
    this page reachable beyond your LAN with no login) - each with a
    one-click fix.
  - Every card in **Media sources**, **Displays & outputs**, and **Artwork
    & metadata** has a "Hide" link if you don't use that plugin type - it
    disappears from the list (and doesn't affect whether it's enabled).
    Hidden ones collapse into a small "Hidden (N)" row at the top of the
    section with one click each to bring them back. This is a per-instance
    config-UI preference (`ui_hidden_types` in config.yaml, not modeled by
    `Config` at all), so it applies no matter which device opens the page
    and never needs a restart.
  - **Media sources** has one card per source type (essential fields up
    front, the rest under "Advanced settings"), a secret field shows
    "Configured"/"Not set" rather than the credential itself (see
    "Secrets" below), a "Test connection" button, and the `appletv` card's
    pairing wizard (same flow as `python -m mediainfo auth appletv` - scan,
    pair, enter/confirm PIN - with no shell/docker-exec access needed). A
    dedicated **Source priority** panel lists enabled sources in priority
    order (drag-and-drop, or the ↑/↓/Remove buttons) and flags any enabled
    source that isn't in the list, since - per `priority:` below - such a
    source is simply never used.
  - **Displays & outputs** groups instances under their output type, with
    add/duplicate/remove per instance, an optional cosmetic display name
    (`label`, so "Living room Pixoo" replaces "Instance #2" in the UI),
    content filters (media type/source allow-or-block, active hours) under
    their own "Advanced" toggle with plain-language controls instead of
    raw allow/deny lists, and a screen-off-hours/brightness-schedule editor
    built from time pickers instead of hand-typed "HH:MM-HH:MM=N" strings.
    Instances can only be appended/removed from the end (not reordered),
    so non-form fields like `transforms` on existing instances stay
    attached to the right one.
  - **Artwork & metadata** groups enrichers by purpose (movie/TV artwork,
    ratings & summaries, music artwork & artist info, local media
    services) alongside the cache and poster-store settings.
  - **Idle screen** covers `idle_mode` (priority/random) and an idle-source
    priority panel identical in spirit to source priority, plus one card
    per idle wallpaper source.
  - **Automation & schedules** covers the global timing knobs (poll/
    rotation intervals, backoff, the nothing-playing grace period) and
    failure-alert thresholds - per-display schedules (active hours,
    screen-off hours, brightness) live on that display's own card under
    Displays & outputs instead, since that's where the data actually is.
  - **Library & overrides** and **System status** are, respectively, the
    settings for and a link to the library browser/artwork-overrides pages
    (below), and a read-focused status grid (search, status filters, a
    "retrying" vs. "unavailable" distinction instead of treating routine
    backoff retries as full-blown errors, and per-item "Test connection").
  - **Advanced configuration** holds authentication and logging settings,
    a **Backups** panel to restore config.yaml from an automatic pre-save
    backup (same list as `python -m mediainfo restore-backup --list`), and
    the raw-YAML editor for anything the guided UI doesn't cover yet
    (`transforms`, `posters.entries`, and any hand-edited comments) - saves
    from here go through the exact same `Config.from_dict()` validation as
    the guided form, so nothing invalid can be written from either place.
  - **Secrets** (`api_key`, `token`, `password`, ...) are never sent to the
    browser in cleartext: the API reports only whether one is currently
    set, and leaving a secret field alone preserves it unchanged - you only
    ever overwrite one by typing a new value, or explicitly clicking
    "Clear".
  - A sticky save bar appears whenever there are unsaved changes, with
    Save/Discard and a plain-language note on whether the change applies
    within a few seconds or needs a restart. `outputs` changes (added/
    removed/reconfigured instances) always need a restart, since outputs
    are only instantiated once at startup - sources/enrichers/idle sources
    apply via the existing hot-reload instead. The "Restart now" action
    sends SIGTERM to this process - the same signal `docker stop`/Ctrl-C
    already trigger - so it comes back up automatically under a supervisor
    (Docker's `restart: unless-stopped`, already set up in
    docker-compose.yml) but just exits if run unsupervised.
  - `ui: dashboard` (default `form`) only changes which section this
    instance's `/` shows by default (System status instead of Overview) -
    every section is always reachable on every instance via the sidebar
    (or `/form`/`/dashboard` directly), regardless of `ui`. Neither view is
    lower-risk to expose - both can read and write config.yaml, including
    credentials - see SECURITY.md before exposing either beyond a trusted
    local network.
- **`outputs.pixoo`**: IP address of your Pixoo64 (Divoom app → device
  settings).
- **`outputs.web`**: host/port for the local web page. Each browser/screen
  that connects (over the same port) gets its own independent rotation
  through the available images - randomized order, randomized timing -
  rather than every screen seeing an identical broadcast, so multiple
  screens pointed at the same URL don't all show the same picture at the
  same time. Each image change uses a randomly picked transition (fade,
  slide from any side, or zoom); `transition_exclude` (a list of names)
  drops any of them from the pool - this output, `info`, and `video` all
  support it.
- **`outputs.folder`**: `dir` is a local directory that mirrors all of the
  current item's artwork (album art, fanart, posters) as individual image
  files, named after each image's label (e.g. `Poster (fanart.tv).jpg`).
  The folder's contents are replaced whenever the playing item changes, and
  cleared while idle - so it always reflects "what's playing right now".
  Useful for e.g. a digital photo frame that displays whatever's in a
  folder. When running in Docker, mount this directory as a volume to
  access it from the host (already set up in `docker-compose.yml`).
- **`outputs.nest_hub`**: casts the current artwork to a Google Nest Hub
  (or other Chromecast-compatible display) using the Google Cast protocol.
  `device_ip` is the Nest Hub's IP address. Since Cast devices load media
  via an HTTP URL rather than a direct push, this output also runs its own
  small HTTP server (on `server_port`, default 8092) that serves the
  current image - set `server_host` to this machine's LAN address so the
  Nest Hub can reach it (the port is exposed in `docker-compose.yml`).
  While idle (and no idle wallpaper source is configured), the Nest Hub's
  cast session is stopped so it returns to its normal ambient display.
- **`outputs.ulanzi`**: shows the current item as scrolling text on a Ulanzi
  TC001 (or other [AWTRIX3](https://blueforcer.github.io/awtrix3/)) display,
  via its local HTTP API - no artwork is sent. `device_ip` is the device's
  IP address; `app_name` names the AWTRIX3 "custom app" used (default
  `now_playing`). Text format depends on media type: music shows
  "Artist - Song", movies show "Title (Year)", and episodes show
  "Show s01e01". The custom app is removed (returning to the normal clock
  face) while idle. For music, release/version suffixes (e.g.
  "- 2011 Remaster", "(Live)", "[Deluxe Edition]") are stripped from the
  song title.
- **`outputs.video`**: serves a full-screen web player (`host`/`port`) that
  shows idle stock-footage clips and switches to the current artwork when
  something plays. `source` is `pexels` or `pixabay`; `queries` is a
  comma-separated list of search terms (e.g. `nature,ocean,mountains`); set
  `pexels_api_key` (https://www.pexels.com/api/) or `pixabay_api_key`
  (https://pixabay.com/api/docs/) to match. `batch_size` clips are fetched
  every `refresh_interval_seconds` (Pixabay is capped at 20 per request).
- **`outputs.mqtt`**: publishes the current now-playing state as JSON to
  `topic` on the broker at `host`/`port` (with optional `username`/
  `password`/`qos`) - useful for Home Assistant or other automation. Set
  `ha_discovery: true` for a deeper HA integration: a "mediainfo" device
  with now-playing/artist/album/source sensors, a health-problem
  binary_sensor, a hitster-safe switch HA can read *and* set, and a
  refresh-artwork button - all via MQTT Discovery, no YAML needed on the
  HA side.
- **`outputs.feed`**: serves RSS (`/rss`) and Atom (`/atom`) feeds
  describing only the currently playing item (single entry, replaced
  whenever it changes, empty while idle), with artwork as an enclosure,
  plus an HTML discovery page at `/`. `title` names the feed. The entry's
  description includes the Wikipedia summary (see `enrichers.wikipedia`)
  when one was found for that item.
- **`outputs.info`**: `host`/`port` (default 8093) for a web page pairing
  the current artwork with its bio/plot summary - artist bio for music,
  movie info, or TV show info, supplied by `enrichers.wikipedia`. No image
  transforms are applied by default, so artwork is shown at its original
  resolution rather than scaled down as on the small physical displays.
- **`idle.unsplash`**: comma-separated `queries` to pull wallpapers from
  while nothing is playing. `batch_size` wallpapers are downloaded every
  `rotation_interval_seconds`, and each output rotates through that batch
  independently (using the top-level `rotation_interval_seconds`). Requires
  a free `access_key` from https://unsplash.com/oauth/applications.
- **`idle.pexels`**: same shape as `idle.unsplash` above (`queries`,
  `batch_size`, `rotation_interval_seconds`), backed by Pexels instead -
  free `api_key` from https://www.pexels.com/api/ (the same key also
  works for `outputs.video`'s Pexels clips, if that's enabled). Enabling
  this alongside `idle.unsplash` gives an automatic fallback: both are
  fetched independently on their own schedule, and `idle_priority` (see
  above) decides which one's wallpapers actually show if both have some
  ready - so if one is unreachable, the other's still show instead of
  nothing.
- **`idle.local`**: shows random pictures from your own collection -
  no API key, no network. `dir` is a base directory; each of its
  immediate subdirectories is treated as one "destination" (e.g. one
  folder per trip or location, organize them however you like, including
  further subfolders within a destination). Each batch picks ONE
  destination at random and `batch_size` pictures at random from within
  it - pictures from different destinations are never shown in the same
  batch.
- **`idle.lastfm`**: shows album art from `username`'s recent Last.fm
  scrobbles while nothing is playing - `batch_size` recent tracks are
  fetched every `rotation_interval_seconds` (deduplicated by album art, so
  fewer wallpapers than `batch_size` may actually be shown). Requires a
  free `api_key` from https://www.last.fm/api/account/create (the same key
  as `enrichers.lastfm`, if that's also enabled).
- **`idle.library`**: shows cover art from `batch_size` random albums in
  the local music library (see `library:` below) while nothing is
  playing, refreshed every `rotation_interval_seconds`. No API key
  required; only shows albums that have a known MusicBrainz id (e.g. from
  `import-lidarr`).
- **`enrichers.fanarttv`**: free `api_key` from https://fanart.tv/get-an-api-key/.
- **`enrichers.thetvdb`**: free `api_key` from
  https://thetvdb.com/dashboard/account/apikey (only "user-supported" keys
  need a `pin`). Sources that already know a show's tvdb id (Kodi,
  Jellyfin/Emby, Plex) use it directly; sources that only know a title
  (e.g. the Shield source, for SVT Play) get it resolved by name via
  thetvdb's own search, cached in memory for the process's lifetime. List
  this enricher before `enrichers.fanarttv` so the resolved id is also
  available to fanart.tv's TV branch. A bare title search is ambiguous
  for common names (several unrelated shows are all called "Kingdom") -
  when more than one candidate comes back, the episode subtitle (reported
  as `"<number>. <episode title>"` by e.g. the Shield source) is checked
  against each candidate's actual episode list (including a Swedish
  translation, for SVT Play) before trusting one. If no candidate's
  episode list can be verified this way, no artwork is added rather than
  guessing - showing a wrong show's poster is worse than showing none -
  and a log line explains why (e.g. "could not verify any of 5
  candidates for 'Kingdom' ..."). `max_search_candidates` (default 5)
  controls how many search results get checked this way before giving
  up; raise it to catch a correct match thetvdb's search ranks further
  down, at the cost of more API calls for generic titles.
- **`enrichers.sonarr`**: matches the playing episode against your own
  [Sonarr](https://sonarr.tv/) library (by tvdb id, falling back to an
  exact title match) and adds its network as `NowPlaying.studio`, plus a
  poster/fanart. Get the `api_key` from Sonarr's Settings → General →
  Security.
- **`enrichers.radarr`**: matches the playing movie against your own
  [Radarr](https://radarr.video/) library (by tmdb id, falling back to an
  exact title match) and adds its studio (`NowPlaying.studio`) and genres
  (`NowPlaying.genres`), plus a poster/fanart. Get the `api_key` from
  Radarr's Settings → General → Security.
- **`enrichers.lidarr`**: matches the playing artist against your own
  [Lidarr](https://lidarr.audio/) library (by exact name match) and adds
  album art for the playing album, plus a list of the artist's other
  albums/songs (`NowPlaying.discography`, capped at
  `max_discography_items`). Get the `api_key` from Lidarr's Settings →
  General → Security. This is a live per-play lookup, distinct from
  `python -m mediainfo import-lidarr` (see `library.db_path` below), which
  bulk-imports Lidarr's MusicBrainz ids once into the local cache.
- **`enrichers.discogs`**: free personal access `token` from
  https://www.discogs.com/settings/developers. Adds album cover art for
  music by searching Discogs by artist + album name; only runs when both
  are known, to avoid matching the wrong release.
- **`enrichers.lastfm`**: free `api_key` from
  https://www.last.fm/api/account/create. Adds an artist photo for music.
- **`enrichers.wikipedia`**: no API key required (free public REST API).
  Searches Wikipedia for the artist (music), movie, or TV show, and adds
  a plain-text summary (`NowPlaying.summary`) plus a thumbnail photo. The
  summary is shown by the `info` output and included in RSS/Atom feed
  entries.
- **`enrichers.library`**: no API key required. For sources that don't
  report an album at all (e.g. YouTube), looks up the playing artist+song
  in the local music library and adds cover art for every album the song
  appears on (a song on more than one release - the original album, a
  singles compilation, a remaster, ... - gets art for all of them, not
  just one). List it before the other music enrichers in `enrichers:` so
  that if it fills in the album name unambiguously, they get a chance to
  also contribute art for it.
- **`enrichers.ai_artwork`**: optional, off by default. Generates an
  album-art-style image for the playing song via a local Stable-
  Diffusion-WebUI-API-compatible instance (`host`/`port` -
  AUTOMATIC1111 and most SD/SDXL forks; not ComfyUI, whose API is
  shaped differently). Prompted from a short mood (if
  `text_enrichers.ollama_text` populated one) and/or genre - never from
  lyrics. Generated images are cached per song under
  `cache.dir/ai_artwork`, so a song is only ever generated once.
- **`text_enrichers.lrclib`**: no API key required (free public
  https://lrclib.net API). Looks up plain and time-synced lyrics for the
  currently playing music track (`NowPlaying.lyrics`/`synced_lyrics`),
  cached locally under `cache.dir/text`. Never shows a guessed or
  fuzzy-matched result - if LRCLIB has nothing for the track (or it's
  instrumental), lyrics are simply left blank.
- **`text_enrichers.ollama_text`**: optional, off by default. Generates
  short mood/description/"did you know"/album-artist context text
  (`NowPlaying.ai_text`) about the playing song using a local Ollama
  instance you run yourself (`host`/`port`/`model` - the model must
  already be pulled, e.g. `ollama pull llama3.2`). Only ever sends
  metadata (artist/title/album/genres/year) to the model - never lyrics.
  `timeout_seconds` bounds how long one (usually cached-after-first-play)
  generation may take.
- **`cache.dir`**: where downloaded artwork is stored.
- **`cache.min_width`** / **`cache.min_height`**: any downloaded image
  smaller than this (default 640×480) is rejected - not cached, and
  re-tried on the next poll instead of being shown - since low-res
  thumbnails (a fallback icon some APIs return when they have no real
  artwork) aren't worth displaying full-screen. Set both to `0` to
  disable the check entirely. Manual artwork overrides (see `overrides`
  below) are exempt, since those are a deliberate choice rather than a
  downloaded fallback.
- **`cache.max_age_days`**: how long unused cached now-playing artwork is
  kept before being deleted (default 30).
- **`cache.idle_max_age_hours`**: how long unused cached idle wallpapers
  (Unsplash, Last.fm scrobble history) are kept before being deleted
  (default 48) - much shorter than `max_age_days`, since they're
  decorative and easily refetched rather than tied to a specific item.
  Stored separately under `<cache.dir>/idle`. Music artwork (album art,
  artist photos) is stored separately too, under `<cache.dir>/music` -
  unlike movie/TV posters and fanart, it's never purged at all, since the
  same handful of albums/artists tend to get replayed indefinitely and
  re-fetching them is just wasted API calls.
- **`library.db_path`** / **`library.max_age_days`**: a local SQLite
  database of artist/album/track metadata (MusicBrainz ids, cached cover
  art URLs, artist photos), queried before the `musicbrainz`,
  `fanarttv`, `discogs`, and `lastfm` enrichers make an external
  API call - so the same artist/album/song doesn't trigger a repeat lookup
  across plays or process restarts. MusicBrainz is treated as the source
  of truth for canonical ids; other sources' results are cached (including
  a "nothing found" result, to avoid retrying known dead ends) for
  `max_age_days` (default 30) before being looked up again. If you run
  [Lidarr](https://lidarr.audio/), `python -m mediainfo import-lidarr
  --config config.yaml --url http://lidarr-host:8686 --api-key
  YOUR_LIDARR_API_KEY` (or the `docker compose run` equivalent, with
  `--config config/config.yaml`) imports its already-verified
  artist/album/track MusicBrainz ids in bulk, so the enrichers have
  everything cached up front instead of discovering it one play at a
  time. Artist/album/track name matching is fuzzy-tolerant (case,
  accents, "&" vs "and", and punctuation are ignored), so a source
  reporting "Simon and Garfunkel" still matches a library entry imported
  as "Simon & Garfunkel". Browse/search the library at `/library` on the
  `config` output's port (e.g. http://localhost:8094/library).
- **`logging.level`**: `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, or
  `CRITICAL`. Switch to `DEBUG` when troubleshooting why a source isn't
  detecting playback - it logs things like each Sonos coordinator
  checked/skipped, which are normally too noisy for everyday use.
- **`logging.file`** / **`logging.max_bytes`** / **`logging.backup_count`**:
  optionally also write logs to a rotating file (logs always go to
  stdout, visible via `docker compose logs`).
- **`auth`**: optional HTTP Basic Auth for the `web`/`config`/`info`/
  `feed`/`video`/`nest_hub` outputs, off by default (`enabled: false`).
  When turned on, requests from RFC1918 private-use addresses and
  loopback are still never challenged - only requests from outside those
  ranges need `username`/`password` - so your own LAN keeps working with
  no login prompt either way. Turn this on if you're exposing one of
  these outputs beyond your LAN (port-forwarding, a reverse proxy, a VPN
  you don't fully trust, ...). One shared username/password applies to
  all of them. See SECURITY.md for more on this. Changing `auth` (from
  the config UI's "Advanced configuration" page, or by hand) needs a
  restart to take effect - every Flask-based output's login check is only
  set up once, at startup.

  #### Resetting the config UI password

  If you've forgotten the password (or are locked out of the page that
  would otherwise let you change it), reset it from the command line
  instead of hand-editing config.yaml:

  ```bash
  python -m mediainfo set-password --config config.yaml
  # or, running under Docker:
  docker compose run --rm mediainfo python -m mediainfo set-password --config config/config.yaml
  ```

  Prompts for a new password (twice, to confirm) so it never appears in
  your shell history; pass `--username NAME` to also change the username,
  or `--password` non-interactively if you're scripting this. Preserves
  comments/formatting in config.yaml and validates the result before
  writing, same as every other way of editing it. Leaves `auth.enabled`
  untouched unless you pass `--enable` - so resetting an existing password
  can't accidentally turn authentication on. **Restart afterwards** (same
  caveat as above) for the new password to actually take effect.
- **`alerts`**: off by default (`enabled: false`). When enabled, `webhook_url`
  gets a JSON POST once an output has been continuously failing for at
  least `error_threshold_seconds` (default 5 minutes) - e.g. a Pixoo64
  that's gone unreachable on the network. Most chat tools (Slack, Discord,
  ntfy.sh, healthchecks.io, or any endpoint of your own that accepts a
  plain JSON POST) work as the webhook target. Re-fires at most every
  `repeat_interval_seconds` (default 1 hour) while the outage continues,
  and resets the moment the output recovers, so a long outage doesn't spam
  the webhook but also doesn't get silently forgotten about.
- **`overrides`**: on by default (`enabled: true`). Lets you pin a specific
  image for a title/subtitle that never gets a good poster from any
  enricher (matched by exact title + subtitle, case-insensitive) - manage
  these from the config UI's "Overrides" page (`http://<host>:8094/overrides`),
  no YAML editing needed: upload an image, type the title (and subtitle,
  if applicable - leave blank for e.g. a movie with no subtitle), save.
  A match replaces whatever enrichment found for that item entirely, and
  isn't subject to the 640×480 minimum-size check other downloaded
  artwork goes through, since it's a deliberate choice rather than an
  automatic download. `dir` is where the uploaded images are stored.

## Extending with new sources/outputs/enrichers

1. Add a config dataclass in `mediainfo/config/sources.py` (or `outputs.py`,
   `enrichers.py`, `idle.py`) and register it in that module's
   `SOURCE_CONFIG_TYPES` (or `OUTPUT_CONFIG_TYPES`, `ENRICHER_CONFIG_TYPES`,
   `IDLE_CONFIG_TYPES`).
2. Add a new module under `mediainfo/sources/` (or `outputs/`, or
   `idle/`) that implements `MediaSource.get_now_playing()` (or
   `Output.update()` / `on_idle()`, or
   `IdleWallpaperSource.get_wallpapers()`), returning a
   `mediainfo.models.NowPlaying` (or a list of `Artwork`).
3. Register it in `SOURCE_CLASSES` (or `OUTPUT_CLASSES`, `ENRICHER_CLASSES`,
   `IDLE_CLASSES`) in `mediainfo/registries.py`, as a dotted import-path
   string (e.g. `"mediainfo.sources.kodi.KodiSource"`) rather than the
   class itself - these are resolved lazily on first use, so adding a
   source doesn't force every plugin's own dependencies to be imported
   up front just to build this dict.
4. Add it to `priority` (sources), `outputs` (outputs), `enrichers`
   (enrichers), or `idle` (idle wallpaper sources) in your `config.yaml`.

Each source's `get_now_playing()` must catch its own connection errors and
return `None` rather than raising, so one unreachable source never breaks
the polling loop. Set `self.last_poll_failed = True` when that `None` was
caused by a connection failure (device unreachable), and `False` when it
connected fine and simply found nothing playing - the orchestrator uses
this to back off polling frequency (starting at `backoff_initial_seconds`
[default 30s], doubling up to `backoff_max_seconds` [default 5 minutes] -
both configurable at the top level of `config.yaml`) for sources whose
device is unreachable, without delaying detection for sources that are
just legitimately idle.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Linting and type checking

```bash
ruff check mediainfo vinyl_recognizer tests
mypy mediainfo
```
