"""Dashboard UI for the config output (`outputs.config[].ui: dashboard`).

A read-focused alternative to the full editable form: sources/outputs/
enrichers with their live status (from the same data /health uses),
client-side filtering, and a per-item "test connection" button. Meant for
running a second config output instance dedicated to "is everything
working", e.g. without exposing config.yaml's write access on that port.

Test-connection implementation notes:
- Sources: a fresh instance is constructed from the live config and
  polled once via get_now_playing() - the exact same call the
  orchestrator itself makes every tick, so there's no separate "test"
  code path to fall out of sync with real polling.
- Enrichers: each has its own lightweight check using its own internal
  request methods against a well-known real item (e.g. "Queen" for music
  enrichers), since the public enrich() interface swallows its own
  errors by design and can't distinguish "API down" from "legitimately
  nothing found for this item".
- Outputs: a plain TCP (or HTTP, for outputs that are themselves servers)
  reachability check against whatever host/ip/port the dashboard already
  displays for that instance - never re-sends an actual update, so a test
  click can't visibly disrupt a physical display.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, Optional, Tuple

import requests

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
    from mediainfo.__main__ import SOURCE_CLASSES

    cls = SOURCE_CLASSES.get(name)
    if cls is None or source_config is None:
        return False, "Unknown source"

    loop = None
    try:
        instance = cls(source_config)
        loop = getattr(instance, "_loop", None)  # appletv's background asyncio loop
        result = instance.get_now_playing()
        if getattr(instance, "last_poll_failed", False):
            return False, "Could not connect - check host/credentials"
        if result is not None:
            return True, f"Connected - currently playing: {result.title}"
        return True, "Connected - nothing currently playing"
    except Exception as exc:
        return False, f"Error: {exc}"
    finally:
        # Best-effort cleanup for sources that start a background thread
        # on construction (only Apple TV, today) - it's a daemon thread so
        # it won't block shutdown, but a repeatedly-clicked test button
        # shouldn't leak one of these every time.
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass


def test_enricher(name: str, enricher_config: Any) -> Tuple[bool, str]:
    if enricher_config is None:
        return False, "Unknown enricher"

    try:
        if name == "thetvdb":
            from mediainfo.enrichers.thetvdb import TheTvDbEnricher

            token = TheTvDbEnricher(enricher_config)._login()
            return (token is not None, "Logged in successfully" if token else
                    "Login failed - check api_key/pin")

        if name == "fanarttv":
            from mediainfo.enrichers.fanarttv import FanartTvEnricher

            # 5cd0fc20-c2eb-4fe8-9d4c-49a8e35a2e29 isn't needed - fanart.tv
            # looks up music by mbid; "The Matrix"'s TMDB id is a stable,
            # well-known test target for the movie branch of this API.
            data = FanartTvEnricher(enricher_config)._get("movies/603")
            return (data is not None, "API reachable" if data else
                    "No response - check api_key")

        if name == "discogs":
            from mediainfo.enrichers.discogs import DiscogsEnricher

            url = DiscogsEnricher(enricher_config)._find_cover("Queen", "A Night at the Opera")
            return True, ("Found cover art for test query" if url else
                          "Reached Discogs, no match for test query (token may still be invalid)")

        if name == "lastfm":
            from mediainfo.enrichers.lastfm import LastFmEnricher

            url = LastFmEnricher(enricher_config)._fetch_artist_image("Queen")
            return True, ("Found artist photo for test query" if url else
                          "Reached Last.fm, no photo for test query (token may still be invalid)")

        if name == "musicbrainz":
            from mediainfo.enrichers.musicbrainz import _query_musicbrainz

            result = _query_musicbrainz("Queen", "A Night at the Opera")
            return (result is not None, "Resolved test query successfully" if result else
                    "No match for test query (musicbrainz.org may be unreachable)")

        if name == "wikipedia":
            from mediainfo.enrichers.wikipedia import WikipediaEnricher

            result = WikipediaEnricher(enricher_config)._lookup(["Queen (band)", "Queen"])
            return (result is not None, "Found summary for test query" if result else
                    "No match for test query (en.wikipedia.org may be unreachable)")

        if name == "library":
            return True, "Local library - no network connection to test"
    except Exception as exc:
        return False, f"Error: {exc}"

    return False, "No connection test available for this enricher"


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
            port = fields.get("port")
            if not port:
                return False, "No port configured"
            return _http_check(fields.get("host") or "127.0.0.1", int(port))
    except Exception as exc:
        return False, f"Error: {exc}"

    return False, "No connection test available for this output"


def _tcp_check(host: str, port: int, timeout: float = 3.0) -> Tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"Reached {host}:{port}"
    except Exception as exc:
        return False, f"Could not reach {host}:{port} ({exc})"


def _http_check(host: str, port: int, timeout: float = 3.0) -> Tuple[bool, str]:
    address = "127.0.0.1" if host in ("0.0.0.0", "") else host
    url = f"http://{address}:{port}/"
    try:
        response = requests.get(url, timeout=timeout)
        return response.status_code < 500, f"HTTP {response.status_code} from {url}"
    except Exception as exc:
        return False, f"Could not reach {url} ({exc})"
