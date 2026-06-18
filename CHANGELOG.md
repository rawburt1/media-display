# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Fixed
- `ImageCache` now sends a descriptive `User-Agent` header when downloading
  artwork. Wikimedia (used by the Wikipedia enricher's thumbnails) rejects
  the default python-requests User-Agent with a 403, so those photos were
  silently failing to download.

### Added
- The `config` output's web form now supports multiple instances of
  multi-instance-capable outputs (e.g. two `ulanzi` displays), with
  "+ Add instance" / "- Remove last" controls per output type. Previously
  only the first instance of any list-configured output was editable in
  the form. Instances can only be appended/removed from the end (not
  reordered) so non-form fields like `transforms` stay attached to the
  right instance when saving.
- `mediainfo/sources/youtube.py`: `sources.youtube` source for the YouTube
  app on Android TV (e.g. Nvidia Shield), via ADB. Unlike the generic
  `shield` source, this targets YouTube specifically and only reports
  "now playing" when the video looks like a song - either the channel
  follows YouTube's "`Artist` - Topic" auto-generated convention, or the
  video title itself follows "`Artist` - `Song`" - so other video content
  is ignored. Once detected, the existing music enrichers (fanart.tv/
  MusicBrainz/Last.fm/Discogs/Wikipedia) take over for artwork/bio info.
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
