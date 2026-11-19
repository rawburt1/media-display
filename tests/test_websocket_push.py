"""Tests for the shared WebSocket client-tracking/broadcast plumbing."""

import threading
from unittest.mock import MagicMock

import pytest
from flask import Flask
from flask_sock import Sock

from mediainfo.outputs import websocket_push
from mediainfo.outputs.websocket_push import (
    _PING_INTERVAL_SECONDS,
    ClientRegistry,
    describe_user_agent,
    summarize_payload,
    broadcast,
    register_websocket_route,
    send_to_one,
)


def _app_with_sock():
    app = Flask(__name__)
    sock = Sock(app)
    return app, sock


def test_register_websocket_route_configures_ping_interval():
    app, sock = _app_with_sock()
    register_websocket_route(
        sock,
        "/ws",
        threading.Lock(),
        set(),
        get_initial_payload=lambda conn: {},
    )

    assert app.config["SOCK_SERVER_OPTIONS"]["ping_interval"] == _PING_INTERVAL_SECONDS


def test_register_websocket_route_preserves_other_server_options():
    app, sock = _app_with_sock()
    app.config["SOCK_SERVER_OPTIONS"] = {"max_message_size": 1024}

    register_websocket_route(
        sock,
        "/ws",
        threading.Lock(),
        set(),
        get_initial_payload=lambda conn: {},
    )

    assert app.config["SOCK_SERVER_OPTIONS"]["max_message_size"] == 1024
    assert app.config["SOCK_SERVER_OPTIONS"]["ping_interval"] == _PING_INTERVAL_SECONDS


def test_broadcast_sends_to_all_clients():
    conn_a, conn_b = MagicMock(), MagicMock()
    clients = {conn_a, conn_b}

    broadcast(threading.Lock(), clients, {"hello": "world"})

    conn_a.send.assert_called_once()
    conn_b.send.assert_called_once()


def test_broadcast_drops_dead_clients_and_reports_them():
    conn_alive, conn_dead = MagicMock(), MagicMock()
    conn_dead.send.side_effect = OSError("closed")
    clients = {conn_alive, conn_dead}
    dropped = []

    broadcast(threading.Lock(), clients, {}, on_drop=dropped.append)

    assert conn_dead not in clients
    assert conn_alive in clients
    assert dropped == [conn_dead]


def test_send_to_one_drops_on_failure():
    conn = MagicMock()
    conn.send.side_effect = OSError("closed")
    clients = {conn}
    dropped = []

    send_to_one(threading.Lock(), clients, conn, {}, on_drop=dropped.append)

    assert conn not in clients
    assert dropped == [conn]


# ---------------------------------------------------------------------------
# ClientRegistry (/clients page)
# ---------------------------------------------------------------------------

_CHROME_LINUX = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


@pytest.fixture
def no_dns(monkeypatch):
    """Reverse DNS must never hit the network in tests - and run inline so
    results are deterministic."""
    monkeypatch.setattr(websocket_push.socket, "gethostbyaddr", lambda addr: ("tv.lan", [], [addr]))

    class _Inline:
        def __init__(self, target, args=(), daemon=None):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(websocket_push.threading, "Thread", _Inline)


def test_summarize_idle_and_wallpaper_and_clock():
    assert summarize_payload({})["mode"] == "idle"
    assert summarize_payload({"source": "idle", "title": "x"})["mode"] == "wallpaper"
    assert summarize_payload({}, idle_label="Ordklocka") == {"mode": "clock", "text": "Ordklocka"}
    assert summarize_payload({"source": "idle"}, idle_label="Ordklocka")["mode"] == "clock"


def test_summarize_playing():
    s = summarize_payload({"source": "kodi", "media_type": "music", "title": "T", "subtitle": "A"})
    assert s == {"mode": "playing", "text": "T – A", "media_type": "music", "source": "kodi"}
    assert summarize_payload({"source": "plex", "title": "Film"})["text"] == "Film"


def test_describe_user_agent():
    assert describe_user_agent(_CHROME_LINUX) == "Chrome på Linux (ARM)"
    assert describe_user_agent("Mozilla/5.0 (Linux; Android 9) CrKey/1.56") == "Chromecast"
    assert describe_user_agent("") == "Okänd"


def test_registry_tracks_connection_and_last_payload(no_dns):
    reg = ClientRegistry()
    conn = object()
    reg.add(conn, page="/", remote_addr="192.168.1.20", user_agent=_CHROME_LINUX)
    [entry] = reg.snapshot()
    assert entry["showing"]["mode"] == "unknown"
    assert entry["hostname"] == "tv.lan"
    assert entry["device"] == "Chrome på Linux (ARM)"

    reg.note_sent(conn, {"source": "kodi", "title": "Song"})
    [entry] = reg.snapshot()
    assert entry["showing"]["mode"] == "playing"
    assert entry["last_sent_at"] is not None

    reg.remove(conn)
    assert reg.snapshot() == []


def test_registry_uses_route_summarizer(no_dns):
    reg = ClientRegistry()
    conn = object()
    reg.add(
        conn,
        page="/ordklocka",
        remote_addr="",
        user_agent="",
        summarize=lambda p: {"mode": "clock", "text": "Ordklocka"},
    )
    reg.note_sent(conn, {})
    assert reg.snapshot()[0]["showing"]["mode"] == "clock"


def test_registry_survives_failed_reverse_dns(monkeypatch, no_dns):
    def boom(addr):
        raise OSError("no PTR")

    monkeypatch.setattr(websocket_push.socket, "gethostbyaddr", boom)
    reg = ClientRegistry()
    reg.add(object(), page="/", remote_addr="10.0.0.5", user_agent="")
    assert reg.snapshot()[0]["hostname"] is None


def test_note_sent_for_unknown_conn_is_ignored():
    ClientRegistry().note_sent(object(), {"title": "x"})


def test_broadcast_and_send_to_one_record_payload(monkeypatch, no_dns):
    reg = ClientRegistry()
    monkeypatch.setattr(websocket_push, "CLIENTS", reg)
    conn = MagicMock()
    reg.add(conn, page="/", remote_addr="", user_agent="")
    broadcast(threading.Lock(), {conn}, {"source": "kodi", "title": "A"})
    assert reg.snapshot()[0]["showing"]["text"] == "A"
    send_to_one(threading.Lock(), {conn}, conn, {})
    assert reg.snapshot()[0]["showing"]["mode"] == "idle"


def test_two_websocket_routes_can_share_a_blueprint():
    from flask import Blueprint

    app, sock = _app_with_sock()
    bp = Blueprint("multi", __name__)
    for path in ("/ws", "/ordklocka/ws"):
        register_websocket_route(
            sock, path, threading.Lock(), set(), get_initial_payload=lambda conn: {}, bp=bp
        )
    app.register_blueprint(bp)
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert {"/ws", "/ordklocka/ws"} <= rules
