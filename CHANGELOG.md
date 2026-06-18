# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- `mediainfo/enrichers/wikipedia.py`: Wikipedia enricher adding an artist
  bio / movie info / TV show info summary (`NowPlaying.summary`) plus a
  thumbnail photo, via the free public Wikipedia REST API (no API key).
- `mediainfo/outputs/info.py`: high-resolution `info` output (default port
  8093) pairing the current artwork with its Wikipedia summary text. No
  image transforms are applied by default, so artwork is shown at its
  original resolution.
- Feed output (`outputs.feed`, RSS/Atom) now includes the Wikipedia summary
  in each entry's description when one was found.
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
