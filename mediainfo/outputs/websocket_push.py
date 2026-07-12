"""Shared WebSocket client-tracking and broadcast plumbing for outputs that
push JSON state to a persistent /ws connection (web.py, info.py).

Deliberately function-based rather than a class that owns the client set
and lock itself: web.py's per-client rotation bookkeeping needs to mutate
its own extra state (_client_rotation) atomically alongside the client
set, under the *same* lock acquisition - encapsulating the set behind its
own object would either block that or just hand the lock back out anyway.
These functions take the caller's own set/lock as arguments instead, so
each output's existing locking semantics are unchanged; only the
literally-duplicated logic (broadcasting, dropping dead connections, the
connect/receive-loop/disconnect shape) is shared.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from mediainfo.models import NowPlaying

logger = logging.getLogger(__name__)


def add_playback_position(payload: dict, now_playing: NowPlaying) -> None:
    """Add position/duration to a WebSocket payload when the source reports
    them (see NowPlaying.position_seconds - None means "unknown"). The page
    advances its progress bar locally between pushes, since payloads only
    go out on item changes and rotation ticks, not every poll.
    """
    if now_playing.duration_seconds and now_playing.position_seconds is not None:
        payload["position_seconds"] = now_playing.position_seconds
        payload["duration_seconds"] = now_playing.duration_seconds


# Keep the underlying connection alive through NAT/firewall idle timeouts,
# and - more importantly - reliably detect one that's gone dead without a
# clean close (e.g. the client's network dropped silently, as can happen
# after a laptop sleeps or a Wi-Fi blip): a missed pong closes the
# connection server-side, which the client's own onclose handler then
# reconnects from. Without this, a long-lived kiosk display's connection
# can sit "open" but defunct indefinitely - showing stale state forever,
# since plain TCP gives no other signal of that - until something forces
# a manual page reload.
_PING_INTERVAL_SECONDS = 20


def broadcast(
    clients_lock,
    clients: set,
    payload: dict,
    on_drop: Optional[Callable[[Any], Any]] = None,
) -> None:
    """Send `payload` to every client, dropping (and optionally reporting
    via `on_drop`) any that fail to send."""
    data = json.dumps(payload)
    with clients_lock:
        snapshot = list(clients)
    dead: set = set()
    for conn in snapshot:
        try:
            conn.send(data)
        except Exception:
            dead.add(conn)
    if dead:
        with clients_lock:
            clients -= dead
            if on_drop:
                for conn in dead:
                    on_drop(conn)


def send_to_one(
    clients_lock,
    clients: set,
    conn: Any,
    payload: dict,
    on_drop: Optional[Callable[[Any], Any]] = None,
) -> None:
    """Send `payload` to a single client, dropping it (and optionally
    reporting via `on_drop`) on failure."""
    try:
        conn.send(json.dumps(payload))
    except Exception:
        with clients_lock:
            clients.discard(conn)
            if on_drop:
                on_drop(conn)


def register_websocket_route(
    sock,
    path: str,
    clients_lock,
    clients: set,
    get_initial_payload: Callable[[Any], dict],
    on_connect: Optional[Callable[[Any], Any]] = None,
    on_disconnect: Optional[Callable[[Any], Any]] = None,
) -> None:
    """Wire a flask_sock route at `path`: add the connection to `clients`
    (plus an optional `on_connect` hook, run under the same lock
    acquisition so it stays atomic with the add - e.g. web.py assigning a
    new client's rotation state), send an initial payload so a fresh
    page-load or reconnect doesn't wait for the next push, then block on
    `conn.receive()` until the client disconnects (discarding it from
    `clients`, plus an optional `on_disconnect` hook, again atomically).
    """
    sock.app.config.setdefault("SOCK_SERVER_OPTIONS", {})["ping_interval"] = _PING_INTERVAL_SECONDS

    @sock.route(path)
    def _handler(conn):
        with clients_lock:
            clients.add(conn)
            if on_connect:
                on_connect(conn)
        try:
            conn.send(json.dumps(get_initial_payload(conn)))
            while True:
                conn.receive()
        except Exception:
            pass
        finally:
            with clients_lock:
                clients.discard(conn)
                if on_disconnect:
                    on_disconnect(conn)
