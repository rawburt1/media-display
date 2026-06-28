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
    """Wire up a before_request hook enforcing HTTP Basic Auth for
    requests from outside the private/loopback ranges. No-op if `config`
    is None or `config.enabled` is False.
    """
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
