# Configuration guide

Most of this is easiest done from the config UI (`http://<this-machine>:8090/config`
- see `outputs.config` below) rather than by hand. See `config.example.yaml`
for every available option if you're editing YAML directly - `config.yaml`
itself starts out as a copy of `config.starter.yaml` (just the config UI and
a few harmless local outputs, no sources), not the full example file. Key
things to fill in:

## General settings

- **`config_version`**: schema version of the file, currently `3`. Safe to
  leave out entirely (an absent version is treated as `1` and migrated
  forward automatically, e.g. dropping the per-output `host`/`port` keys
  `config_version: 2` removed, and `config_version: 3` hashing a plaintext
  `auth.password`) - it exists so a future field rename can transparently
  upgrade old config.yaml files instead of rejecting them at startup. You
  should never need to set this by hand; just don't remove it if a future
  upgrade adds/bumps it. Note that migration only happens in memory on
  load - it doesn't rewrite config.yaml itself, so an old file keeps
  working (and keeps its old on-disk shape) until you next save it via the
  config UI or `set-password`.
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

## Sources

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
  token at `cache_path`. Reports whichever device is actively playing
  account-wide (Spotify Connect), including device name and playback
  progress. **If you authorized before this device/progress support was
  added**, re-run the `auth spotify` command above once - the cached token
  needs the broader `user-read-playback-state` scope now, and a stale one
  is rejected with a log message telling you to redo this step rather than
  a cryptic API error.
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
- **`sources.browser`**: unlike every other source, this one doesn't poll
  anything - it runs its own small WebSocket server (`host`/`port`, default
  `0.0.0.0:8096`) that the companion [browser
  extension](../browser-extension/) connects to and pushes now-playing state
  into whenever a supported site (YouTube, Spotify Web, Netflix, Disney+,
  SVT Play, Plex Web) is playing in a tab. Set `token` here and in the
  extension's options page if this port is reachable by anyone besides
  you - there's no other authentication. `timeout` (default 10s) is how
  long a tab's last update stays valid before being treated as idle, since
  there's no polling to notice a browser that's simply gone quiet (tab
  closed, browser closed, network drop). See
  [browser-extension/README.md](../browser-extension/README.md) for
  installation and per-site limitations.
- **`sources.homeassistant`**: tracks `media_player` entity state via
  Home Assistant's WebSocket API (a persistent, push-based subscription,
  not polling) - `host`/`port`/`use_ssl` point at HA itself, `token` is a
  long-lived access token (HA UI: your profile → Security → Long-lived
  access tokens → Create Token), and `entity_id` is the entity to track
  (HA UI: Settings → Devices & Services → Entities) - leave it blank to
  track every media_player entity instead and report whichever one is
  actually playing. Not specific to Apple TV - this works for any device
  HA tracks - but its main use is as a fallback for `sources.appletv`:
  list it right after `appletv` in `priority` so it only gets consulted
  once appletv has confirmed pyatv itself sees nothing playing, for an
  app like SVT Play that HA's own Apple TV integration can apparently
  still see (likely via an MRP pairing made back when the device still
  advertised that protocol - pairing fresh today only offers Companion/
  AirPlay, which expose far less now-playing metadata to third-party
  clients).
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
- **`sources.vinyl`**: host/port of a [vinyl_recognizer](../vinyl_recognizer/)
  instance - a separate service that runs on the machine a Behringer UCA202
  (or similar USB audio interface) is connected to, listens to a turntable's
  output, and identifies the playing track via [AudD](https://audd.io/). See
  `vinyl_recognizer/README.md` for setup.

## Outputs

- Any entry under `outputs` can be a single config (as below) or a list of
  configs, to run multiple instances of that output at once - e.g. several
  Ulanzi displays in different rooms, or several `web`/`nest_hub` instances.
  Every Flask-based output (`web`, `config`, `themes`, `info`, `feed`,
  `video`, `nest_hub`) shares one HTTP server (`http:` - see
  `config.example.yaml`); if you add a second instance of one of those
  types, give it a unique `label` (e.g. `label: bedroom`) so it mounts at
  its own path (`/video-bedroom`) instead of colliding with the first.
- **`outputs.config`**: served under `/config` on the shared HTTP server
  (`http://<this-machine>:8090/config` by default) - a guided web app
  that configures mediainfo without needing to know YAML - a single-page
  shell (sidebar nav on desktop, a hamburger menu on narrow screens) with
  nine sections: Overview, Media sources, Displays & outputs, Artwork &
  metadata, Idle screen, Automation & schedules, Library & overrides,
  System status, and Advanced configuration. It's generated automatically
  from the source/output/enricher/idle config dataclasses, so a new plugin
  type gets a card with no UI code to write - only a friendly label/
  description/help text needs adding (see `_TYPE_INFO`/`_FIELD_HELP` in
  `mediainfo/configui/config_schema.py`) for it to read well, and it still
  works without those.
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
    credentials - see [SECURITY.md](../SECURITY.md) before exposing either beyond a
    trusted local network.
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
- **`outputs.themes`**: served under `/themes` on the shared HTTP server -
  the separate Display Themes display (see above), a broadcast page, not
  per-client-rotated like `web`.
  `themes:` (nested inside this section) holds one entry per individual
  theme, keyed by theme name - see config.example.yaml for the currently
  available themes and their own options (just `color_palette` today).
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
  via an HTTP URL rather than a direct push, this output serves the current
  image under `/nest_hub` on the shared HTTP server - set `server_host` to
  this machine's LAN address so the Nest Hub can reach it (the port is
  exposed in `docker-compose.yml` as part of `http:`). While idle (and no
  idle wallpaper source is configured), the Nest Hub's cast session is
  stopped so it returns to its normal ambient display.
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
- **`outputs.video`**: serves a full-screen web player (under `/video` on
  the shared HTTP server) that shows idle stock-footage clips and switches
  to the current artwork when something plays. `source` is `pexels` or
  `pixabay`; `queries` is a
  comma-separated list of search terms (e.g. `nature,ocean,mountains`); set
  `pexels_api_key` (https://www.pexels.com/api/) or `pixabay_api_key`
  (https://pixabay.com/api/docs/) to match. `batch_size` clips are fetched
  every `refresh_interval_seconds` (Pixabay is capped at 20 per request).
- **`outputs.mqtt`**: publishes the current now-playing state as JSON to
  `topic` on the broker at `host`/`port` (with optional `username`/
  `password`/`qos`) - useful for Home Assistant or other automation. Set
  `ha_discovery: true` for a deeper HA integration: a "mediainfo" device
  with now-playing/artist/album/source sensors, a health-problem
  binary_sensor, a hitster-safe switch HA can read *and* set, a
  refresh-artwork button, a next-image button (advances rotation
  immediately), and a restart button - all via MQTT Discovery, no YAML
  needed on the HA side.
- **`outputs.feed`**: serves RSS (`/feed/rss`) and Atom (`/feed/atom`) feeds
  describing only the currently playing item (single entry, replaced
  whenever it changes, empty while idle), with artwork as an enclosure,
  plus an HTML discovery page at `/feed`. `title` names the feed. The
  entry's description includes the Wikipedia summary (see
  `enrichers.wikipedia`) when one was found for that item.
- **`outputs.info`**: served under `/info` on the shared HTTP server - a web
  page pairing the current artwork with its bio/plot summary - artist bio for music,
  movie info, or TV show info, supplied by `enrichers.wikipedia`. No image
  transforms are applied by default, so artwork is shown at its original
  resolution rather than scaled down as on the small physical displays.

## Idle wallpapers

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

## Enrichers

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

## Text enrichers

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

## Cache and library

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
  as "Simon & Garfunkel". Browse/search the library at `/library` under the
  `config` output's path (e.g. http://localhost:8090/config/library).

## Logging

- **`logging.level`**: `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, or
  `CRITICAL`. Switch to `DEBUG` when troubleshooting why a source isn't
  detecting playback - it logs things like each Sonos coordinator
  checked/skipped, which are normally too noisy for everyday use.
- **`logging.file`** / **`logging.max_bytes`** / **`logging.backup_count`**:
  optionally also write logs to a rotating file (logs always go to
  stdout, visible via `docker compose logs`).

## Authentication

- **`auth`**: optional HTTP Basic Auth for the `web`/`config`/`info`/
  `feed`/`video`/`nest_hub` outputs, off by default (`enabled: false`).
  When turned on, requests from RFC1918 private-use addresses and
  loopback are still never challenged - only requests from outside those
  ranges need `username`/`password` - so your own LAN keeps working with
  no login prompt either way. Turn this on if you're exposing one of
  these outputs beyond your LAN (port-forwarding, a reverse proxy, a VPN
  you don't fully trust, ...) - and put a TLS-terminating reverse proxy in
  front of this app when you do, since Basic Auth sends credentials
  Base64-encoded, not encrypted, on every request (see [SECURITY.md](../SECURITY.md)). One
  shared username/password applies to all of them. Changing `auth` (from
  the config UI's "Advanced configuration" page, or `set-password` below)
  needs a restart to take effect - every Flask-based output's login check
  is only set up once, at startup.

  `password` is stored hashed - set it via the config UI or `set-password`
  below, not by hand-editing config.yaml (there's no way to write a valid
  hash yourself).

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

## Alerts

- **`alerts`**: off by default (`enabled: false`). When enabled, `webhook_url`
  gets a JSON POST once an output has been continuously failing for at
  least `error_threshold_seconds` (default 5 minutes) - e.g. a Pixoo64
  that's gone unreachable on the network. Most chat tools (Slack, Discord,
  ntfy.sh, healthchecks.io, or any endpoint of your own that accepts a
  plain JSON POST) work as the webhook target. Re-fires at most every
  `repeat_interval_seconds` (default 1 hour) while the outage continues,
  and resets the moment the output recovers, so a long outage doesn't spam
  the webhook but also doesn't get silently forgotten about.

## Manual artwork overrides

- **`overrides`**: on by default (`enabled: true`). Lets you pin a specific
  image for a title/subtitle that never gets a good poster from any
  enricher (matched by exact title + subtitle, case-insensitive) - manage
  these from the config UI's "Overrides" page
  (`http://<host>:8090/config/overrides`), no YAML editing needed: upload
  an image, type the title (and subtitle, if applicable - leave blank for
  e.g. a movie with no subtitle), save.
  A match replaces whatever enrichment found for that item entirely, and
  isn't subject to the 640×480 minimum-size check other downloaded
  artwork goes through, since it's a deliberate choice rather than an
  automatic download. `dir` is where the uploaded images are stored.
