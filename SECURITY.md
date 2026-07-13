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

By default none of the HTTP outputs (web/config/info/feed/video/Nest Hub)
require authentication, which is fine as long as they're only ever
reachable from your own LAN. If you expose any of them beyond it
(port-forwarding, a reverse proxy, a VPN you don't fully trust, ...), set
`auth.enabled: true` in `config.yaml` (see README.md) first - it requires
HTTP Basic Auth for any request whose source address isn't an RFC1918
private-use or loopback address, so your LAN keeps working without a
login prompt while anything reaching these outputs from outside it does
need one.

Every Flask-based output shares one HTTP server and one `host`/`port`
(`http:` in `config.yaml` - see README.md), so there is no way to bind an
individual output differently from the others: `http.host: 0.0.0.0` (the
shipped default) makes every enabled output, including `config`, reachable
from the whole LAN; `http.host: 127.0.0.1` makes all of them loopback-only,
including `web`, the display most people want reachable from another
device in the first place. If you want the now-playing display reachable
from the LAN but the config UI locked down, disable `outputs.config`
(or don't enable it in the first place) and turn it on temporarily from the
host itself when you need to make a change, or rely on `auth.enabled: true`
instead - see below.

The `config` output (`outputs.config`, see README.md) is a special case:
it has read **and write** access to `config.yaml`, including whatever
credentials are stored in it. Anyone who can reach `/config` on the shared
HTTP server (and isn't blocked by `auth`, if enabled) can read your API
keys/tokens and change any setting. Only enable it on a trusted local
network, or behind `auth`.

**This output is reachable on your LAN, with no login, out of the box.**
Both `config.starter.yaml` (what `setup.sh` copies into `config/config.yaml`
on a fresh install) and `config.example.yaml` set `http.host` to `0.0.0.0`,
and `docker-compose.yml` publishes that one port by default - this is
deliberate, so a new install is reachable from a browser with zero YAML
editing (see README.md "Quick start"), but it means anyone else on your
LAN can read every API key in `config.yaml` from the moment the container
starts. If your home network isn't fully trusted (e.g. a shared/student
flat, an untrusted IoT VLAN you haven't segmented this machine out of),
set `auth.enabled: true` before or immediately after first boot - the
config UI's own "Advanced configuration" page can do this for you, no
restart-then-edit-YAML dance needed except the restart itself (see
README.md's `auth` section). Set `http.host: 127.0.0.1` instead if you
never need to reach any of these outputs from another device at all -
Docker users note that this makes them unreachable even from the Docker
host itself (see "Operating modes at a glance" below).

## Cross-site request protection

A LAN source address being exempt from `auth` (above) says nothing about whether a
request was actually initiated by someone on your LAN - a malicious webpage a household
member's browser visits can still fire a state-changing request at, e.g.,
`http://192.168.1.x:8090/config/api/config/form`, and it looks identical to a legitimate one. Two
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

## HTTP Basic Auth: hashed at rest, plaintext on the wire without TLS

`auth.password` is stored hashed in `config.yaml` (as of `config_version: 3`
- see README.md), not plaintext - set it via `python -m mediainfo
set-password` or the config UI, both of which hash it for you. An older
config file with a plaintext password is transparently upgraded in memory
the moment it's loaded, so the running process never compares a submitted
password against plaintext even before the file itself is next resaved.

That protects the credential *at rest*. It does **not** protect it in
transit: HTTP Basic Auth sends `username:password` Base64-encoded (not
encrypted) on every single request - trivially reversible by anyone able
to observe the traffic between a client and this app (a shared coffee-shop
Wi-Fi, an untrusted hop on the public internet, a compromised router,
...). `auth.enabled: true` over plain HTTP stops casual/opportunistic
access to a URL, but does not protect the password itself once real
network observation is in play.

**If you're exposing any of these outputs beyond a network you fully
trust, put a TLS-terminating reverse proxy in front of this app** rather
than relying on `auth.enabled` alone over plain HTTP. This app has no
built-in TLS support (see H1's rationale for using `werkzeug.serving`,
not a production TLS-capable server, in
`mediainfo/outputs/http_server.py`) - terminating TLS is explicitly a
reverse proxy's job here. Any of the common options work the same way:
the proxy holds the certificate and speaks HTTPS to the outside world,
then forwards plain HTTP to this app's `http.host`/`http.port` (or, more
simply, to `127.0.0.1` if the proxy runs on the same machine). A minimal
Caddy example (automatic HTTPS via Let's Encrypt):

```
mediainfo.example.com {
    reverse_proxy 127.0.0.1:8090
}
```

nginx or Traefik work equivalently - point them at whichever host/port
`http:` in `config.yaml` is bound to, and terminate TLS in front of it.
Set `http.host: 127.0.0.1` on this app once a reverse proxy is the only
thing meant to reach it directly. Note the Host-allowlist guard mentioned
above: a reverse-proxy setup using a real hostname currently gets
rejected by this app's own `_require_trusted_host` check - open an issue
if you need that combination.

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

These settings apply to every Flask-based output at once (`web`, `config`,
`themes`, `info`, `feed`, `video`, `nest_hub`) - they all share one
`http.host`/`http.port`, so there's no way to make just one of them
(e.g. `config`) more restricted than the rest short of disabling it.

| Setup | Reachable from | Recommended for |
|---|---|---|
| `http.host: 127.0.0.1` | This machine only (Docker: unreachable even from the host - the published port can't reach a loopback-only bind inside the container) | Development, or "never touch this from another device" |
| `http.host: 0.0.0.0`, no `auth` (shipped default) | Entire LAN (no login) | Fully trusted home network |
| `http.host: 0.0.0.0`, `auth.enabled: true` | LAN (login required); public IPs challenge all | Shared/untrusted LAN, or exposing beyond LAN via port-forward/reverse proxy over plain HTTP (login required, but the password itself isn't protected in transit - see above) |
| `http.host: 127.0.0.1`, `auth.enabled: true`, behind a TLS-terminating reverse proxy | Wherever the proxy is reachable from (LAN, VPN, public internet) - login required, password protected in transit | Exposing beyond your LAN for real (see the reverse-proxy section above) |
