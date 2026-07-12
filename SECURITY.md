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

**This output is reachable on your LAN, with no login, out of the box.**
Both `config.starter.yaml` (what `setup.sh` copies into `config/config.yaml`
on a fresh install) and `config.example.yaml` set `outputs.config.host` to
`0.0.0.0`, and `docker-compose.yml` publishes port 8094 by default - this
is deliberate, so a new install is reachable from a browser with zero YAML
editing (see README.md "Quick start"), but it means anyone else on your
LAN can read every API key in `config.yaml` from the moment the container
starts. If your home network isn't fully trusted (e.g. a shared/student
flat, an untrusted IoT VLAN you haven't segmented this machine out of),
set `auth.enabled: true` before or immediately after first boot - the
config UI's own "Advanced configuration" page can do this for you, no
restart-then-edit-YAML dance needed except the restart itself (see
README.md's `auth` section). Set `outputs.config.host: 127.0.0.1` instead
if you never need to reach the config UI from another device at all -
Docker users note that this makes it unreachable even from the Docker
host itself (see "Operating modes at a glance" below).

## Cross-site request protection

A LAN source address being exempt from `auth` (above) says nothing about whether a
request was actually initiated by someone on your LAN - a malicious webpage a household
member's browser visits can still fire a state-changing request at, e.g.,
`http://192.168.1.x:8094/api/config`, and it looks identical to a legitimate one. Two
protections are always active, regardless of whether `auth.enabled` is set, on every
Flask-based output:

- **A required header on state-changing requests.** Every POST/PUT/PATCH/DELETE route
  must carry a custom header this app's own JavaScript always sends. A plain HTML
  `<form>` submission (the classic CSRF vector) can't set custom headers at all, and a
  cross-origin `fetch()`/`XMLHttpRequest` that tries to forces a CORS preflight this app
  never satisfies (it never sends `Access-Control-Allow-Origin` for any origin) - so
  only this app's own same-origin page can get a mutating request through.
- **A Host header allowlist**, to close DNS-rebinding (where an attacker's own hostname
  gets pointed at your LAN IP after the page has already loaded, defeating source-address
  checks entirely): the `Host` header on every request must be `localhost` or a literal
  private/loopback IP address. **This means a reverse-proxy setup using a real hostname
  (e.g. a LAN DNS name or a VPN domain) is not currently allowlisted and will be
  rejected** - if you need that, open an issue.

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
| `host: 127.0.0.1` | This machine only (Docker: unreachable even from the host - the published port can't reach a loopback-only bind inside the container) | Development, or "never touch this from another device" |
| `host: 0.0.0.0`, no `auth` (shipped default) | Entire LAN (no login) | Fully trusted home network |
| `host: 0.0.0.0`, `auth.enabled: true` | LAN (login required); public IPs challenge all | Shared/untrusted LAN, or exposing beyond LAN via port-forward/reverse proxy |
