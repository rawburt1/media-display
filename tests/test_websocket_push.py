"""Tests for the shared WebSocket client-tracking/broadcast plumbing."""

import threading
from unittest.mock import MagicMock

from flask import Flask
from flask_sock import Sock

from mediainfo.outputs.websocket_push import (
    _PING_INTERVAL_SECONDS,
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
        sock, "/ws", threading.Lock(), set(), get_initial_payload=lambda conn: {},
    )

    assert app.config["SOCK_SERVER_OPTIONS"]["ping_interval"] == _PING_INTERVAL_SECONDS


def test_register_websocket_route_preserves_other_server_options():
    app, sock = _app_with_sock()
    app.config["SOCK_SERVER_OPTIONS"] = {"max_message_size": 1024}

    register_websocket_route(
        sock, "/ws", threading.Lock(), set(), get_initial_payload=lambda conn: {},
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
