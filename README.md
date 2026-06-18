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
  protocols), Android TV / Nvidia Shield (via ADB, "now playing" from any
  app), vinyl turntable (audio recognition via
  [vinyl_recognizer](vinyl_recognizer/) + AudD)
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
  including the Wikipedia summary when available
- **Idle wallpapers**: Unsplash - while nothing is playing, downloads a fresh
  batch of wallpapers matching the configured search queries every
  `rotation_interval_seconds`, and each output independently rotates through
  that batch on its own randomized schedule (same as the now-playing artwork
  rotation above)
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

## Configuration

See `config.example.yaml` for all options. Key things to fill in:

- **`priority`**: ordered list of source names. When more than one source
  is active at once, the first one in this list wins.
- **`sources.kodi`**: Kodi host/port and credentials. In Kodi, enable
  *Settings → Services → Control → Allow remote control via HTTP*.
- **`sources.sonos`**: IP address of any Sonos speaker on your network
  (find it in the Sonos app under speaker settings, or your router's
  device list).
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
  `docker compose run --rm mediainfo python -m mediainfo auth spotify`),
  which opens a login flow and caches the token at `cache_path`. Only
  reports playback on the account that's actively listening.
- **`sources.appletv`**: `host` is the Apple TV's IP/hostname. Pair once
  with `python -m mediainfo auth appletv --config config.yaml` (or the
  `docker compose run` equivalent) - follow the prompts to enter the PIN
  shown on the TV, then paste the printed credentials into config.yaml.
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
- **`outputs.pixoo`**: IP address of your Pixoo64 (Divoom app → device
  settings).
- **`outputs.web`**: host/port for the local web page.
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
- **`enrichers.fanarttv`**: free `api_key` from https://fanart.tv/get-an-api-key/.
- **`enrichers.thetvdb`**: free `api_key` from
  https://thetvdb.com/dashboard/account/apikey (only "user-supported" keys
  need a `pin`).
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
- **`cache.dir`**: where downloaded artwork is stored.
- **`cache.max_age_days`**: how long unused cached artwork is kept before
  being deleted (default 30).

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
the polling loop.

## Running tests

```bash
pip install pytest
pytest
```
