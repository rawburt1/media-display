# mediainfo

[![Tests](https://github.com/rawburt1/media-display/actions/workflows/tests.yml/badge.svg)](https://github.com/rawburt1/media-display/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Polls "now playing" media sources on your network and shows the current
album art / poster on a [Divoom Pixoo64](https://divoom.com/) LED display,
a Ulanzi TC001, a Google Nest Hub, a simple local web page, and more.

## Status

Currently implemented:

### Sources

- **Kodi** — movie/episode posters+fanart, music
- **Plex** — movie/episode posters+fanart, music
- **Jellyfin and Emby** — movie/episode posters+fanart, music, via the Sessions API
- **Sonos** — album art
- **Spotify** — current playback via the Web API
- **Mopidy** — music, via its core JSON-RPC API - backend-agnostic, works the same regardless of which Mopidy backend is actually playing
- **MPD / Music Player Daemon** — music, including embedded/folder cover art when the server supports it
- **Logitech Media Server / Squeezebox** — music, auto-selects the active player across a multi-player household unless `player_id` is set
- **VLC** — any media, via VLC's built-in web/HTTP interface - requires enabling it and setting a password in VLC's own preferences
- **foobar2000** — music, via the [Beefweb Remote Control plugin](https://github.com/hyperblast/beefweb)
- **Apple TV** — any app, via the Companion/MRP/AirPlay protocols
- **The YouTube *app* on Android TV** — ⚠️ not YouTube in general: this works only via ADB against an actual Android TV device running the YouTube app, e.g. an Nvidia Shield; it cannot see YouTube played in a browser, on a phone, on a smart TV's own built-in app, or anywhere else. Reports a song only when the video looks like one - see "Extending" below.
- **Android TV / Nvidia Shield** — via ADB, generic "now playing" from any other app on the same device
- **Vinyl turntable** — audio recognition via [vinyl_recognizer](vinyl_recognizer/) + AudD
- **Home Assistant** — polls a single `media_player` entity via HA's REST API - a fallback for devices a more specific source can't read directly, e.g. a tvOS app that doesn't populate Apple's own now-playing API
- **Generic Chromecast/Cast** — polls any configured Cast device's media status directly, so anything cast to it (Netflix, Disney+, YouTube, Spotify Connect, etc.) is picked up regardless of which app is casting, unlike the Shield source which only sees apps running locally on that device
- **Browser extension** (see [browser-extension/](browser-extension/)) — for media playing in a browser tab: YouTube, Spotify Web, Netflix, Disney+, SVT Play, Plex Web - pushed to a small WebSocket server this source runs, rather than polled

### Enrichers

- **fanart.tv** and **thetvdb.com** — extra posters/fanart for movies and TV shows (matched via tmdb/imdb/tvdb ids)
- **fanart.tv** and **Discogs** — also add (and prefer) album covers for music, matched via MusicBrainz ids or, failing that, by looking up the artist/album name (e.g. for Sonos) via the MusicBrainz API or Discogs' search
- **Last.fm** — artist photos
- **Wikipedia** — an artist bio / movie info / TV show info summary plus a photo, for the `info` output and RSS/Atom feeds below
- **Sonarr / Radarr / Lidarr** — each match against your own library (rather than a public catalog) and add a studio/genres/discography plus poster/fanart/album art - see [docs/configuration-guide.md](docs/configuration-guide.md)
- **TMDb** and **OMDb** — each add a 0-10 rating for movies/TV shows, also for the `info` output. Both can be enabled at once without conflict, since neither overwrites a rating the other already found.

### Outputs

- **Pixoo64** (local HTTP API), **web page** (`http://<host>:8090/`), and **Google Nest Hub** (Cast) — each rotate between all available poster/fanart images for the current item on their own randomized schedule; each one picks its own shuffled order, so they don't all show the same image at the same time
- **Folder export** — mirrors all of the current item's artwork to a local directory
- **Ulanzi TC001** (AWTRIX3) — shows the current item as scrolling text instead of artwork (e.g. "Artist - Song", "Title (Year)", "Show s01e01")
- **Video output** — serves a full-screen web player that shows idle stock-footage clips (Pexels/Pixabay) and switches to artwork when something plays
- **Info output** (`http://<host>:8090/info`) — pairs the current artwork at its original (high) resolution with the Wikipedia summary text
- **MQTT** — publishes now-playing state to a broker topic
- **Feed output** — serves RSS/Atom feeds describing only the currently playing item, including the Wikipedia summary when available
- **Config output** (`http://<host>:8090/config`) — a web page for editing every config option above (sources, outputs, enrichers, idle sources, polling intervals, including most list-valued fields like Sonos speaker IPs) without hand-editing YAML. Saved changes are hot-reloaded within a few seconds, and it has a "Hitster-safe" button that suppresses song/artist/album display across *every* output (falling back to idle wallpapers/text instead) while it's on, so a song's title/artist never leaks onto a screen mid-round of Hitster or similar music-guessing games.
- **Themes output** (`http://<host>:8090/themes`) — a completely separate full-screen display from `web` that layers selectable, combinable Display Themes on top of the current artwork; enabled themes render simultaneously into one combined look. Off by default. `outputs.themes[].auto_rotate` can optionally cycle between named presets (subsets of the enabled themes) on a timer, instead of always showing all of them at once.

  Ships today with:

  - **Color Palette** — a strip of the artwork's dominant colors
  - **Blurred Background** — a heavily blurred, darkened copy of the artwork filling the screen behind it
  - **Word Cloud** — built from lyrics for music, or the plot summary for movies/TV, colored from the artwork (reuses the same cached word cloud described under `mediadata` below for music)
  - **Glow** — a soft, slowly pulsing ambient glow behind the artwork, colored from it
  - **Ken Burns** — a slow, continuous pan/zoom on the artwork, the classic documentary effect
  - **Vinyl** — shows the album art as a spinning record (music only)
  - **Media Mosaic** — a grid of other artwork for the same item - other albums, other posters/fanart - alongside the current pick
  - **Timeline** — a list of the artist's other albums (music only, needs `enrichers.lidarr` configured or it just shows the current album)
  - **Equalizer** — a decorative bar/wave animation suggesting audio activity (music only, not driven by a real audio signal)
  - **Lyrics Ticker** — a karaoke-style ticker highlighting the current line of time-synced lyrics (music only, needs synced lyrics available e.g. via `text_enrichers.lrclib`)
  - **Now Playing Progress** — a real-data full-width playback progress border along one screen edge (works for music, movies, and TV alike)
  - **Cast/Crew Mosaic** — a grid of top-billed cast headshots (movie/TV only, needs `enrichers.tmdb.fetch_cast` enabled)
  - **Artist Spotlight** — a portrait card with the artist's photo and a short bio blurb

  More themes still being added - see the Display Themes roadmap.

### Idle wallpapers

Sources: **Unsplash**, **Pexels**, **local folders** (random pictures from your own collection - see `idle.local` below), **Last.fm scrobble history** (album art from your recent scrobbles), and/or **your own music library** (random covers from imported albums).

- While nothing is playing, downloads/picks a fresh batch of wallpapers every `rotation_interval_seconds`, and each output independently rotates through that batch on its own randomized schedule (same as the now-playing artwork rotation above).
- Multiple idle sources can be enabled at once, each refetched independently on its own schedule, but they're never mixed within a single batch - `idle_priority` (an ordered list of source names) picks which one supplies any given batch: the first one in that list with wallpapers available wins, so e.g. enabling both Unsplash and Pexels means one being temporarily unreachable falls through to the other instead of blanking outputs.
- `idle_mode: random` (instead of the default `priority`) picks the winning source at random each batch instead of always preferring the same one first - either way, exactly one source's pictures show per batch, never blended.
- The last successfully-fetched batch is also persisted to disk and reloaded on restart, so a source being down right when the process restarts doesn't blank outputs either, as long as the previous batch's cached image files haven't since been purged (see `cache.idle_max_age_hours`).

### Other features

- **Manual artwork overrides** — pin a specific image for a title/subtitle that never gets a good poster from any enricher, via the config UI's "Overrides" page. On by default (`overrides.enabled: true`).
- **Alerting** — optionally POST a webhook (Slack, Discord, ntfy.sh, healthchecks.io, or any endpoint that accepts JSON) once an output has been continuously failing for a while (e.g. a Pixoo64 that's gone unreachable on the network). Off by default, see `alerts` below.
- **Disk cache** for downloaded artwork (each image is only fetched once, and unused files are purged after `cache.max_age_days`).
- **`/health` endpoint** (on the web output) — reports uptime, the current now-playing item, and per-source/output/enricher status. JSON by default, or an HTML dashboard when requested with `Accept: text/html`. The JSON payload is a versioned schema (`schema_version`) - see `docs/health-api-reference.md` for the full field-by-field reference if you're scripting against it.
- **`mediadata`** — a unified, human-browsable on-disk cache (`mediainfo/media_data_store.py`) organizing artwork/lyrics/metadata as `movies/<Title> (<Year>)/poster.jpg`, `music/<Artist>/artist.jpg`, `music/<Artist>/<Album> (<Year>)/albumart.jpg`, etc., each with a `metadata.json` recording where each file came from and when it was last checked/refreshed - a cache-first design with a per-media-type refresh policy (`mediadata.refresh`, see config.example.yaml), instead of today's flat `cache/` directory. Off by default (`enrichers.mediadata`/`text_enrichers.mediadata`); when enabled, real fetches happen for movie/series posters+fanart (TMDb, falling back to fanart.tv for movies), music artist photo (Wikipedia, falling back to Last.fm) + album art (MusicBrainz, falling back to Discogs), and lyrics (LRCLIB) - existing `cache/`/`overrides/`/`posters/` are untouched and keep working exactly as before; this doesn't replace them. A further opt-in switch (`enrichers.mediadata.wordcloud.enabled`) renders a lyrics word-cloud PNG per track, colored from its album art, once both are cached - stored next to the track's `.lrc` file and shown on the web output only (not on Pixoo/Nest Hub/etc., where dense text doesn't read well).

## Setup

### Requirements

- **Docker + Docker Compose** (recommended - no Python setup needed), **or**
  Python 3.10+ if you'd rather run it directly on the host.
- At least one supported media source reachable on your network (see
  "Sources" above) and its IP/credentials. You don't need all of them - one
  source and one output is enough to get something on screen; add more
  later by re-editing config.yaml - most changes hot-reload within a few
  seconds (see [docs/configuration-guide.md](docs/configuration-guide.md)
  for the exceptions).

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
| VLC | Set in VLC: Preferences → Lua → Lua HTTP → Password | `sources.vlc` |
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
docker compose up -d
```

`./setup.sh` creates every directory `docker-compose.yml` bind-mounts
(`config/`, `cache/`, `library/`, `logs/`, `adb_keys/`, `artwork/`,
`spotify_cache/`, `overrides/`) and copies `config.starter.yaml` to
`config/config.yaml` if it isn't there yet - a minimal config with just the
config UI and a couple of harmless local outputs enabled, and no sources,
so a fresh install doesn't sit there erroring against placeholder IPs.
Running `setup.sh` yourself first matters: Docker otherwise creates any
missing mount target itself as root, which the container's non-root app
user can't then write into. config.yaml lives in `./config/config.yaml`
rather than the project root because it's bind-mounted as a directory, so
editors/tools that save by replacing the file (rather than writing in
place) don't orphan the mount.

Open `http://<this-machine>:8090/config` - the guided config UI - and add
whichever sources (Kodi, Plex, Spotify, ...) and displays you actually use
from there; no YAML editing needed. Most changes apply within a few
seconds; the page tells you when one needs a restart instead (see
[docs/configuration-guide.md](docs/configuration-guide.md)). Once at least
one source and one output are enabled, `http://<this-machine>:8090/` shows
the artwork/idle wallpaper.

**Prefer hand-editing YAML instead?** `nano config/config.yaml` - see
`config.example.yaml` for every available option, or
[docs/configuration-guide.md](docs/configuration-guide.md).

**Security note**: the config UI has read+write access to every API key in
config.yaml and needs no login by default - fine on a trusted home LAN,
but see [SECURITY.md](SECURITY.md) before this machine's ports are reachable
beyond one (port-forwarding, an untrusted shared network, ...).

Check `docker compose logs -f` if nothing shows up (see "Troubleshooting"
below).

To update later: `git pull && docker compose up -d --build`.

### Manual install (no Docker)

```bash
git clone https://github.com/rawburt1/media-display.git
cd media-display

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.starter.yaml config.yaml
python -m mediainfo --config config.yaml
```

Open `http://<this-machine>:8090/config` - the guided config UI - and add your
sources/displays from there (or `nano config.yaml` - see
`config.example.yaml` for every available option, if you'd rather edit
YAML by hand). The web page is at `http://<this-machine>:8090/` once at
least one source and output are enabled.

To update later: `git pull && pip install -r requirements.txt`.

**Prefer a leaner install?** `pip install -r requirements.txt` installs every
integration's dependency (OpenCV, pyatv, adb-shell, ...) whether you use it or
not. `pip install -e .` instead installs only the core (Flask, Pillow, PyYAML,
pydantic, ...) plus whichever integrations you actually want, via extras named
after each source/output (`pip install -e .[appletv,sonos,pixoo-text-detection]`)
or `pip install -e .[all]` to match the full `requirements.txt` install. A
source/output whose dependency isn't installed is skipped with a clear log
message at startup rather than crashing the app - see pyproject.toml for the
full list of extras.

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
  in [docs/configuration-guide.md](docs/configuration-guide.md)
  (`python -m mediainfo auth spotify` / `auth appletv`) - run via
  `docker compose run --rm mediainfo python -m mediainfo auth spotify
  --config config/config.yaml` if using Docker.
- **Forgot the config UI password / locked out**: `python -m mediainfo
  set-password --config config.yaml` resets it from the command line - see
  "Resetting the config UI password" under `auth` in
  [docs/configuration-guide.md](docs/configuration-guide.md).
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

Most of this is easiest done from the config UI
(`http://<this-machine>:8090/config`) rather than by hand. `config.yaml`
starts out as a copy of `config.starter.yaml` (just the config UI and a
couple of harmless local outputs, no sources) - see `config.example.yaml`
for a narrative, worked-example config with every available option and
inline comments.

- **[docs/configuration-guide.md](docs/configuration-guide.md)** - a
  field-by-field narrative guide: every source/output/enricher/idle-wallpaper
  setting, `auth`, `alerts`, `overrides`, `cache`, `library`, and config
  versioning/hot-reload behavior.
- **[docs/config-reference.md](docs/config-reference.md)** - an
  auto-generated flat table of every field's type/default/required/secret
  status, generated from the config dataclasses
  (`scripts/generate_config_reference.py`).

## Extending

See [docs/extending.md](docs/extending.md) for adding a new
source/output/enricher/idle-wallpaper plugin.

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
