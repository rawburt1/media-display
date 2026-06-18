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
  via the Web API), Apple TV (any app, via the Companion/MRP/AirPlay
  protocols), YouTube on Android TV (via ADB, reports a song only when the
  video looks like one - see "Extending" below), Android TV / Nvidia Shield
  (via ADB, generic "now playing" from any other app), vinyl turntable
  (audio recognition via [vinyl_recognizer](vinyl_recognizer/) + AudD)
- **Enrichers**: fanart.tv and thetvdb.com add extra posters/fanart for
  movies and TV shows (matched via tmdb/imdb/tvdb ids); fanart.tv and
  Discogs also add (and prefer) album covers for music, matched via
  MusicBrainz ids or, failing that, by looking up the artist/album name
  (e.g. for Sonos) via the MusicBrainz API or Discogs' search; Last.fm adds
  artist photos; Wikipedia adds an artist bio / movie info / TV show info
  summary plus a photo, for the `info` output and RSS/Atom feeds below
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
  Wikipedia summary text; MQTT publishes now-playing state to a broker
  topic; feed output serves RSS/Atom feeds of recently-played items,
  including the Wikipedia summary when available; config output
  (`http://<host>:8094/`) is a web page for editing every config option
  above (sources, outputs, enrichers, idle sources, polling intervals)
  without hand-editing YAML - saved changes are hot-reloaded within a
  few seconds
- **Idle wallpapers**: Unsplash, or Last.fm scrobble history (album art from
  your recent scrobbles) - while nothing is playing, downloads a fresh batch
  of wallpapers every `rotation_interval_seconds`, and each output
  independently rotates through that batch on its own randomized schedule
  (same as the now-playing artwork rotation above). Only one idle source
  can be active at a time.
- Disk cache for downloaded artwork (each image is only fetched once,
  and unused files are purged after `cache.max_age_days`)
- `/health` endpoint (on the web output) reports uptime, the current
  now-playing item, and per-source/output/enricher status - JSON by default,
  or an HTML dashboard when requested with `Accept: text/html`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml
# edit config.yaml with your devices' IPs/credentials

python -m mediainfo --config config.yaml
```

The web page is then available at `http://<this-machine>:8090/`.

Running via `docker compose` instead (see `docker-compose.yml`)? Put
config.yaml in `./config/config.yaml` rather than the project root - it's
bind-mounted as a directory there (`cp config.example.yaml
config/config.yaml`), so editors/tools that save by replacing the file
(rather than writing in place) don't orphan the mount.

## Configuration

See `config.example.yaml` for all options. Key things to fill in:

- **`priority`**: ordered list of source names. When more than one source
  is active at once, the first one in this list wins. A source that's
  `enabled: true` but missing from this list is never actually polled -
  logged as a warning at startup and on every config reload, so this
  mistake doesn't fail silently.
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
  etc.) via the Companion/MRP/AirPlay protocols.
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
- **`sources.youtube`**: same `host`/`port`/ADB pairing flow as
  `sources.shield` above (can point at the same device - use a separate
  `adb_key_path`), but targets the YouTube app specifically rather than
  whatever app is in the foreground, reporting the video title and channel
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
- **`outputs.config`**: `host`/`port` (default 8094) for a web page that
  edits config.yaml itself - every source/output/enricher/idle source and
  the top-level polling intervals, generated automatically from their
  config dataclasses. Outputs (the only category that supports multiple
  instances of the same type, e.g. two `ulanzi` displays) get "+ Add
  instance" / "- Remove last" controls in the form - instances can only be
  appended/removed from the end, not reordered, so that non-form fields
  like `transforms` on existing instances stay attached to the right one.
  List-typed fields themselves (`transforms`, `blacklist`) still aren't
  shown as individual form fields; use the page's "Advanced" raw-YAML
  editor for those. Saves are validated before being written, and the
  running process picks up the change via its existing hot-reload within
  a few seconds. This output can read and write config.yaml, including any
  credentials in it, with no authentication of its own - see SECURITY.md
  before exposing it beyond a trusted local network. The page also has a
  "Restart" button - sources/enrichers/idle sources apply automatically
  via hot-reload, but `outputs` changes (added/removed/reconfigured
  instances) only take effect after a restart, since outputs are only
  instantiated once at startup. It works by sending SIGTERM to the
  process - the same signal `docker stop`/Ctrl-C already trigger - so it
  comes back up automatically under a supervisor (Docker's
  `restart: unless-stopped`, already set up in docker-compose.yml) but
  just exits if run unsupervised. The `appletv` source's card also has a
  "Pair" button that drives the same pairing flow as
  `python -m mediainfo auth appletv` (scan, begin pairing, enter the PIN
  or confirm one shown on screen, finish) and saves the resulting
  credentials directly - no shell/docker-exec access needed.
- **`outputs.pixoo`**: IP address of your Pixoo64 (Divoom app → device
  settings).
- **`outputs.web`**: host/port for the local web page. Each browser/screen
  that connects (over the same port) gets its own independent rotation
  through the available images - randomized order, randomized timing -
  rather than every screen seeing an identical broadcast, so multiple
  screens pointed at the same URL don't all show the same picture at the
  same time.
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
  `password`/`qos`) - useful for Home Assistant or other automation.
- **`outputs.feed`**: serves RSS (`/rss`) and Atom (`/atom`) feeds of
  recently-played items, with artwork as enclosures, plus an HTML
  discovery page at `/`. `max_items` caps how many recent items are kept
  in memory (default 50); `title` names the feed. Each entry's description
  includes the Wikipedia summary (see `enrichers.wikipedia`) when one was
  found for that item.
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
  available to fanart.tv's TV branch.
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
- **`cache.dir`**: where downloaded artwork is stored.
- **`cache.max_age_days`**: how long unused cached now-playing artwork is
  kept before being deleted (default 30).
- **`cache.idle_max_age_hours`**: how long unused cached idle wallpapers
  (Unsplash, Last.fm scrobble history) are kept before being deleted
  (default 48) - much shorter than `max_age_days`, since they're
  decorative and easily refetched rather than tied to a specific item.
  Stored separately under `<cache.dir>/idle`.
- **`library.db_path`** / **`library.max_age_days`**: a local SQLite
  database of artist/album/track metadata (MusicBrainz ids, cached cover
  art URLs, artist photos), queried before the `musicbrainz`, `fanarttv`,
  `discogs`, and `lastfm` enrichers make an external API call - so the
  same artist/album/song doesn't trigger a repeat lookup across plays or
  process restarts. MusicBrainz is treated as the source of truth for
  canonical ids; other sources' results are cached (including a "nothing
  found" result, to avoid retrying known dead ends) for `max_age_days`
  (default 30) before being looked up again. If you run
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
  all of them. See SECURITY.md for more on this.

## Extending with new sources/outputs

1. Add a config dataclass in `mediainfo/config.py` and register it in
   `SOURCE_CONFIG_TYPES` (or `OUTPUT_CONFIG_TYPES`, or `IDLE_CONFIG_TYPES`
   for idle wallpaper sources).
2. Add a new module under `mediainfo/sources/` (or `outputs/`, or
   `idle/`) that implements `MediaSource.get_now_playing()` (or
   `Output.update()` / `on_idle()`, or
   `IdleWallpaperSource.get_wallpapers()`), returning a
   `mediainfo.models.NowPlaying` (or a list of `Artwork`).
3. Register the class in `SOURCE_CLASSES` (or `OUTPUT_CLASSES`, or
   `IDLE_CLASSES`) in `mediainfo/__main__.py`.
4. Add it to `priority` (sources), `outputs` (outputs), or `idle` (idle
   wallpaper sources) in your `config.yaml`.

Each source's `get_now_playing()` must catch its own connection errors and
return `None` rather than raising, so one unreachable source never breaks
the polling loop. Set `self.last_poll_failed = True` when that `None` was
caused by a connection failure (device unreachable), and `False` when it
connected fine and simply found nothing playing - the orchestrator uses
this to back off polling frequency (starting at 30s, doubling up to 5
minutes) for sources whose device is unreachable, without delaying
detection for sources that are just legitimately idle.

## Running tests

```bash
pip install pytest
pytest
```
