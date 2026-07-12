"""Optional HTTP Basic Auth for Flask-based outputs (web, config, info,
feed, video, nest_hub), exempting RFC1918 private-use addresses and
loopback by default - see `auth:` in config.example.yaml. Off entirely
unless `auth.enabled` is true.

Most people only ever reach these outputs from their own LAN; the usual
reason to turn this on is exposing one of them beyond it (port-forwarding,
a reverse proxy, a VPN you don't fully trust, ...). Requiring a login for
every device on your own home network just to see what's playing is a
poor trade-off for that common case, so authentication is only actually
challenged for requests whose source address falls outside the private/
loopback ranges below - your own LAN keeps working exactly as before.

install_auth() also always wires up two more before_request hooks,
regardless of whether auth.enabled - a request's source address being on
the LAN (and so exempt from Basic Auth above) says nothing about whether
the request was actually initiated by someone on the LAN, e.g. a
malicious webpage a household member's browser visits can still fire a
state-changing fetch() at this app's LAN address, and that request looks
identical to a legitimate one:

- _require_csrf_header: state-changing requests (POST/PUT/PATCH/DELETE)
  must carry a custom header this app's own JS always sends. A plain
  <form> POST can't set custom headers at all, and a cross-origin
  fetch()/XHR that tries forces a CORS preflight this app never
  satisfies (no Access-Control-Allow-Origin is ever sent) - so only
  same-origin JS can get past this.
- _require_trusted_host: the Host header must be "localhost" or a
  private/loopback IP literal - closes DNS-rebinding, where an
  attacker's own hostname gets pointed at the victim's LAN IP after the
  page loads. The Host header text is still the attacker's hostname,
  never a private IP literal, even though the request physically
  arrives at a private-IP-bound server. Note: this means a reverse-proxy
  setup using a real hostname is not currently allowlisted - accessing
  through one will be rejected here.
"""

from __future__ import annotations

import ipaddress
from typing import Optional

from flask import Flask, Response, request

from mediainfo.config import AuthConfig

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local addresses
]

_LOOPBACK_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
]

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_CSRF_HEADER_NAME = "X-Requested-With"
_CSRF_HEADER_VALUE = "XMLHttpRequest"


def _host_without_port(host_header: str) -> str:
    """Strip an optional :port suffix off a Host header value - handles a
    bracketed IPv6 literal ("[::1]:8094") as well as plain "host:port"/
    bare "host"."""
    if host_header.startswith("["):
        return host_header[1:].split("]")[0]
    if host_header.count(":") == 1:
        return host_header.split(":")[0]
    return host_header


def is_loopback_address(addr: Optional[str]) -> bool:
    """True for loopback addresses only (127.x.x.x, ::1) — stricter than
    is_private_address, which also includes LAN ranges."""
    if not addr:
        return False
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    return any(ip in network for network in _LOOPBACK_NETWORKS)


def is_private_address(addr: Optional[str]) -> bool:
    """True for RFC1918 private-use addresses, loopback, and IPv6 ULA.

    False (not exempt - auth required if enabled) for anything else,
    including a missing/unparseable address - fail closed.
    """
    if not addr:
        return False
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])  # strip IPv6 zone id, if present
    except ValueError:
        return False
    return any(ip in network for network in _PRIVATE_NETWORKS)


def install_auth(app: Flask, config: Optional[AuthConfig]) -> None:
    """Wire up before_request hooks: the CSRF-header and Host-allowlist
    guards (see module docstring) always, plus HTTP Basic Auth for
    requests from outside the private/loopback ranges when `config` is
    set and `config.enabled` is True.
    """

    @app.before_request
    def _require_csrf_header():
        if (
            request.method in _UNSAFE_METHODS
            and request.headers.get(_CSRF_HEADER_NAME) != _CSRF_HEADER_VALUE
        ):
            return Response("Missing required header", 403)
        return None

    @app.before_request
    def _require_trusted_host():
        host = _host_without_port(request.host)
        if host.lower() != "localhost" and not is_private_address(host):
            return Response("Untrusted Host header", 403)
        return None

    if config is None or not config.enabled:
        return

    @app.before_request
    def _require_auth():
        if is_private_address(request.remote_addr):
            return None
        auth = request.authorization
        if auth and auth.username == config.username and auth.password == config.password:
            return None
        return Response(
            "Authentication required",
            401,
            {"WWW-Authenticate": 'Basic realm="mediainfo"'},
        )
