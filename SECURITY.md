# Security Policy

## Supported Versions

This project does not (yet) cut tagged releases - only the `master` branch
is supported. Please make sure you're running the latest commit before
reporting an issue.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, use GitHub's private reporting:
[Report a vulnerability](https://github.com/rawburt1/media-display/security/advisories/new)
(repo → Security tab → "Report a vulnerability").

Include as much detail as you can: affected source/output/enricher, steps
to reproduce, and potential impact. We'll acknowledge reports as soon as
possible and follow up once a fix is available.

## Scope notes

This app is designed to run on a trusted home/local network and talks to
several third-party APIs and local devices (Kodi, Plex, Jellyfin/Emby,
Sonos, Pixoo64, Ulanzi, Nest Hub, etc.) using credentials/tokens stored in
`config.yaml`. Treat that file - and any cache/token files it references
(e.g. `spotify_cache/token.json`, ADB keys) - as sensitive, and do not
expose this app's HTTP endpoints (web/feed/video/Nest Hub server) to the
public internet without authentication in front of them.
