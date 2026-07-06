"""Small JSON-RPC 2.0-over-HTTP client, shared by sources that speak that
protocol (Mopidy's /mopidy/rpc, Logitech Media Server's /jsonrpc.js).

Kodi (mediainfo/sources/kodi.py) speaks the same protocol but keeps its own
private `_rpc()` method rather than using this - it predates this helper
and is already thoroughly tested, so it's left alone rather than refactored
to match (see "preserve existing behaviour").
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

import requests


class JsonRpcError(RuntimeError):
    """The JSON-RPC response itself carried an "error" field - as opposed
    to a transport-level failure (bad host, timeout, non-2xx status),
    which raises requests' own exception types instead."""


class JsonRpcClient:
    def __init__(self, url: str, auth: Optional[Tuple[str, str]] = None, timeout: float = 5):
        self.url = url
        self.auth = auth
        self.timeout = timeout

    def call(self, method: str, params: Optional[list] = None) -> Any:
        """Call `method` with positional `params` (a list, per JSON-RPC 2.0
        convention - both Mopidy and LMS expect params as an array, not an
        object) and return the "result" field. Raises JsonRpcError for an
        "error" field in the response, or requests' own exceptions for a
        transport-level failure - callers are expected to catch broadly
        and set last_poll_failed, same as every other source.
        """
        payload: dict = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}
        response = requests.post(self.url, json=payload, auth=self.auth, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise JsonRpcError(f"JSON-RPC error calling {method}: {data['error']}")
        return data.get("result")
