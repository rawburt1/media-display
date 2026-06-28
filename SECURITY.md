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
(e.g. `spotify_cache/token.json`, ADB keys) - as sensitive.

By default none of the HTTP outputs (web/config/info/feed/video/Nest Hub
server) require authentication, which is fine as long as they're only
ever reachable from your own LAN. If you expose any of them beyond it
(port-forwarding, a reverse proxy, a VPN you don't fully trust, ...), set
`auth.enabled: true` in `config.yaml` (see README.md) first - it requires
HTTP Basic Auth for any request whose source address isn't an RFC1918
private-use or loopback address, so your LAN keeps working without a
login prompt while anything reaching these outputs from outside it does
need one.

The `config` output (`outputs.config`, see README.md) is a special case:
it has read **and write** access to `config.yaml`, including whatever
credentials are stored in it. Anyone who can reach its port (and isn't
blocked by `auth`, if enabled) can read your API keys/tokens and change
any setting. Only enable it on a trusted local network, or behind `auth`.

Its `host` setting defaults to `127.0.0.1` (loopback only), so it isn't
reachable from the LAN without a deliberate change. When running inside
Docker, set `host: 0.0.0.0` in config.yaml **and** include the management
compose overlay to publish the port:

```
docker compose -f docker-compose.yml -f docker-compose.management.yml up -d
```

## Keeping credentials out of config.yaml

Any string value in config.yaml can reference an environment variable:

```yaml
sources:
  spotify:
    client_secret: ${SPOTIFY_CLIENT_SECRET}
```

Set the variable in your shell, a `.env` file, or Docker Compose's
`environment:` section. The app expands it at startup. If the variable
isn't set, the literal `${SPOTIFY_CLIENT_SECRET}` string is kept and
the startup validator will warn about the unexpanded reference.

## Operating modes at a glance

| Setup | Reachable from | Recommended for |
|---|---|---|
| `host: 127.0.0.1` (default) | This machine only | Single-machine installs, development |
| `host: 0.0.0.0`, no `auth` | Entire LAN (no login) | Fully trusted home network |
| `host: 0.0.0.0`, `auth.enabled: true` | LAN (login required); public IPs challenge all | Exposing beyond LAN via port-forward/reverse proxy |
