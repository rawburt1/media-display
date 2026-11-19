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
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from flask import request

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


# ---------------------------------------------------------------------------
# Connected-client registry (backs the web output's /clients page)
# ---------------------------------------------------------------------------

Summarizer = Callable[[dict], Dict[str, str]]


def summarize_payload(payload: dict, idle_label: Optional[str] = None) -> Dict[str, str]:
    """Describe what a page shows, from the last payload sent to it.

    `idle_label` names what the page shows instead of the idle screen
    (e.g. "Ordklocka" for a web output with idle_clock on).
    """
    if not payload or payload.get("source") == "idle":
        if idle_label:
            return {"mode": "clock", "text": idle_label}
        if payload:
            return {"mode": "wallpaper", "text": "Idle-bild"}
        return {"mode": "idle", "text": "Inget spelas"}
    title = str(payload.get("title") or "")
    subtitle = str(payload.get("subtitle") or "")
    return {
        "mode": "playing",
        "text": f"{title} – {subtitle}" if title and subtitle else title or subtitle,
        "media_type": str(payload.get("media_type") or ""),
        "source": str(payload.get("source") or ""),
    }


def describe_user_agent(user_agent: str) -> str:
    """A rough, human-readable device/browser name from a User-Agent -
    language-neutral ("Chrome · Windows"), since both the Swedish /clients
    page and the English config UI show it. Empty when unknown."""
    ua = user_agent or ""
    if not ua:
        return ""
    if "CrKey" in ua:
        browser = "Chromecast"
    elif "Edg/" in ua:
        browser = "Edge"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "Chrome/" in ua or "Chromium/" in ua:
        browser = "Chrome"
    elif "Safari/" in ua:
        browser = "Safari"
    else:
        browser = ua.split("/", 1)[0][:40]
    if "CrKey" in ua:
        return browser
    for needle, system in (
        ("Android", "Android"),
        ("iPhone", "iPhone"),
        ("iPad", "iPad"),
        ("Windows", "Windows"),
        ("Mac OS X", "Mac"),
        ("CrOS", "ChromeOS"),
        ("aarch64", "Linux (ARM)"),
        ("armv7", "Linux (ARM)"),
        ("Linux", "Linux"),
    ):
        if needle in ua:
            return f"{browser} · {system}"
    return browser


class ClientRegistry:
    """Every open /ws connection across all outputs: where it's from, which
    page it's on, and what it was last sent. Read-only bookkeeping - no
    output's behavior depends on it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: Dict[int, Dict[str, Any]] = {}
        self._summarizers: Dict[int, Summarizer] = {}
        self._hostnames: Dict[str, Optional[str]] = {}

    def add(
        self,
        conn: Any,
        page: str,
        remote_addr: str,
        user_agent: str,
        summarize: Summarizer = summarize_payload,
    ) -> None:
        key = id(conn)
        with self._lock:
            self._entries[key] = {
                "page": page,
                "address": remote_addr,
                "device": describe_user_agent(user_agent),
                "connected_at": time.time(),
                "last_sent_at": None,
                "showing": {"mode": "unknown", "text": ""},
            }
            self._summarizers[key] = summarize
            resolve = bool(remote_addr) and remote_addr not in self._hostnames
            if resolve:
                self._hostnames[remote_addr] = None
        if resolve:
            # Reverse DNS can be slow - never on the connection's own thread.
            threading.Thread(target=self._resolve, args=(remote_addr,), daemon=True).start()

    def _resolve(self, address: str) -> None:
        try:
            name: Optional[str] = socket.gethostbyaddr(address)[0]
        except (OSError, UnicodeError):
            name = None
        with self._lock:
            self._hostnames[address] = name

    def remove(self, conn: Any) -> None:
        with self._lock:
            self._entries.pop(id(conn), None)
            self._summarizers.pop(id(conn), None)

    def note_sent(self, conn: Any, payload: dict) -> None:
        key = id(conn)
        with self._lock:
            entry = self._entries.get(key)
            summarize = self._summarizers.get(key)
        if entry is None or summarize is None:
            return
        try:
            showing = summarize(payload)
        except Exception:
            logger.debug("Could not summarize payload for client list", exc_info=True)
            return
        with self._lock:
            if key in self._entries:
                entry["showing"] = showing
                entry["last_sent_at"] = time.time()

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            items = [
                {**entry, "hostname": self._hostnames.get(entry["address"])}
                for entry in self._entries.values()
            ]
        items.sort(key=lambda e: (e["page"], e["connected_at"]))
        return items


CLIENTS = ClientRegistry()


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
        else:
            CLIENTS.note_sent(conn, payload)
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
    else:
        CLIENTS.note_sent(conn, payload)


def register_websocket_route(
    sock,
    path: str,
    clients_lock,
    clients: set,
    get_initial_payload: Callable[[Any], dict],
    on_connect: Optional[Callable[[Any], Any]] = None,
    on_disconnect: Optional[Callable[[Any], Any]] = None,
    bp=None,
    summarize: Summarizer = summarize_payload,
) -> None:
    """Wire a flask_sock route at `path`: add the connection to `clients`
    (plus an optional `on_connect` hook, run under the same lock
    acquisition so it stays atomic with the add - e.g. web.py assigning a
    new client's rotation state), send an initial payload so a fresh
    page-load or reconnect doesn't wait for the next push, then block on
    `conn.receive()` until the client disconnects (discarding it from
    `clients`, plus an optional `on_disconnect` hook, again atomically).

    `bp`, if given, registers the route on that Blueprint (with its own
    url_prefix applied automatically) instead of directly on `sock.app` -
    see SharedHttpServer (mediainfo/outputs/http_server.py), which gives
    every Flask-based output its own blueprint on one shared app/Sock
    instance rather than each owning its own app.

    Every connection is also listed in CLIENTS (the /clients page), with
    `summarize` turning each payload it's sent into what it shows.
    """
    sock.app.config.setdefault("SOCK_SERVER_OPTIONS", {})["ping_interval"] = _PING_INTERVAL_SECONDS

    # Unique per path, so one blueprint can hold more than one WebSocket
    # route (the web output's /ws and /ordklocka/ws) - "/ws" keeps the
    # original "_handler" endpoint name.
    endpoint = "_handler" if path == "/ws" else "_handler" + path.replace("/", "_")

    @sock.route(path, bp=bp, endpoint=endpoint)
    def _handler(conn):
        page = request.path[: -len("/ws")] if request.path.endswith("/ws") else request.path
        CLIENTS.add(
            conn,
            page=page or "/",
            remote_addr=request.remote_addr or "",
            user_agent=request.headers.get("User-Agent", ""),
            summarize=summarize,
        )
        with clients_lock:
            clients.add(conn)
            if on_connect:
                on_connect(conn)
        try:
            initial = get_initial_payload(conn)
            conn.send(json.dumps(initial))
            CLIENTS.note_sent(conn, initial)
            while True:
                conn.receive()
        except Exception:
            pass
        finally:
            CLIENTS.remove(conn)
            with clients_lock:
                clients.discard(conn)
                if on_disconnect:
                    on_disconnect(conn)
