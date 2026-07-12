"""Dashboard UI for the config output (`outputs.config[].ui: dashboard`).

A read-focused alternative to the full editable form: sources/outputs/
enrichers with their live status (from the same data /health uses),
client-side filtering, and a per-item "test connection" button. Meant for
running a second config output instance dedicated to "is everything
working", e.g. without exposing config.yaml's write access on that port.

Test-connection implementation notes:
- Sources and enrichers: each plugin class implements its own
  test_connection() (see mediainfo/sources/base.py's MediaSource and
  mediainfo/enrichers/base.py's ArtworkEnricher) - this module just looks
  up the class by name and calls it on a fresh instance built from the
  live config. Enrichers need their own internal-method checks against a
  well-known real item (e.g. "Queen" for music enrichers) rather than the
  public enrich() interface, since enrich() swallows its own errors by
  design and can't distinguish "API down" from "legitimately nothing
  found for this item" - each class's own test_connection() handles that.
- Outputs: a plain TCP (or HTTP, for outputs that are themselves servers)
  reachability check against whatever host/ip/port the dashboard already
  displays for that instance - never re-sends an actual update, so a test
  click can't visibly disrupt a physical display. Unlike sources/
  enrichers, this stays a raw field-based check here rather than a class
  method: it runs against unsaved form fields (not a real config object),
  and several outputs need constructor args this dashboard doesn't have
  (e.g. an ImageCache).
- Self-hosted outputs (web/info/feed/video/config): since H1 (see
  docs/architecture-usability-review-2026-07.md), these no longer have
  their own host/port - every Flask-based output shares one HTTP server
  (mediainfo/outputs/http_server.py). Testing "is my own server
  reachable" from inside a page that same server is currently serving is
  close to tautological, so this is a fixed message rather than a real
  network check.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, Tuple

# Local servers this process itself runs - "testing" them means confirming
# the embedded Flask app is actually answering, not reaching some other
# device.
_SELF_HOSTED_OUTPUT_TYPES = {"web", "info", "feed", "video", "config"}

# (output type -> (field holding the address, default port if config has
# no explicit port field)).
_OUTPUT_ADDRESS_FIELDS = {
    "pixoo": ("ip", 80),
    "nest_hub": ("device_ip", 8009),  # Chromecast control port
    "ulanzi": ("device_ip", 80),
}


def test_source(name: str, source_config: Any) -> Tuple[bool, str]:
    from mediainfo import registries

    cls = registries.get_source_class(name)
    if cls is None or source_config is None:
        return False, "Unknown source"

    try:
        return cls(source_config).test_connection()
    except Exception as exc:
        return False, f"Error: {exc}"


def test_enricher(name: str, enricher_config: Any) -> Tuple[bool, str]:
    from mediainfo import registries

    if enricher_config is None:
        return False, "Unknown enricher"

    cls = registries.get_enricher_class(name)
    if cls is None:
        return False, "Unknown enricher"

    try:
        return cls(enricher_config).test_connection()
    except Exception as exc:
        return False, f"Error: {exc}"


def test_output(type_name: str, fields: dict) -> Tuple[bool, str]:
    try:
        if type_name in _OUTPUT_ADDRESS_FIELDS:
            field, default_port = _OUTPUT_ADDRESS_FIELDS[type_name]
            address = fields.get(field)
            if not address:
                return False, f"No {field} configured"
            return _tcp_check(address, int(fields.get("port") or default_port))

        if type_name == "mqtt":
            host, port = fields.get("host"), fields.get("port")
            if not host or not port:
                return False, "No host/port configured"
            return _tcp_check(host, int(port))

        if type_name == "folder":
            directory = fields.get("dir")
            if not directory:
                return False, "No directory configured"
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".connection_test"
            probe.write_text("ok")
            probe.unlink()
            return True, f"{path} is writable"

        if type_name in _SELF_HOSTED_OUTPUT_TYPES:
            return (
                True,
                "Served by the shared HTTP server - reachable, since this page loaded from it.",
            )
    except Exception as exc:
        return False, f"Error: {exc}"

    return False, "No connection test available for this output"


def _tcp_check(host: str, port: int, timeout: float = 3.0) -> Tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"Reached {host}:{port}"
    except Exception as exc:
        return False, f"Could not reach {host}:{port} ({exc})"
