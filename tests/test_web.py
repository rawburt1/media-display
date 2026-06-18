"""Tests for the WebOutput push logic."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mediainfo.config import WebConfig
from mediainfo.models import Artwork, NowPlaying


def _config(**kwargs):
    return WebConfig(enabled=True, host="127.0.0.1", port=8090, **kwargs)


def _music(title="Bohemian Rhapsody", artist="Queen"):
    return NowPlaying(
        source="kodi",
        media_type="music",
        title=title,
        subtitle=artist,
        images=[],
    )


def _artwork(label="Album art"):
    return Artwork(url="https://example.com/art.jpg", label=label)


class _FakeConn:
    def __init__(self):
        self.sent = []
        self.alive = True

    def send(self, data):
        if not self.alive:
            raise OSError("closed")
        self.sent.append(data)

    def receive(self):
        return None


# Suppress the Flask dev-server thread for all tests in this module.
@pytest.fixture(autouse=True)
def no_server(monkeypatch):
    monkeypatch.setattr("threading.Thread.start", lambda self: None)


def _output(config=None):
    from mediainfo.outputs.web import WebOutput
    return WebOutput(config or _config())


# ---------------------------------------------------------------------------
# _get_payload
# ---------------------------------------------------------------------------

def test_payload_when_idle():
    out = _output()
    assert out._get_payload() == {}


def test_payload_when_playing_without_image():
    out = _output()
    out.on_new_item(_music(), MagicMock())
    payload = out._get_payload()
    assert payload["title"] == "Bohemian Rhapsody"
    assert payload["subtitle"] == "Queen"
    assert payload["source"] == "kodi"
    assert "image" not in payload


def test_payload_when_playing_with_image(tmp_path):
    out = _output()
    np = _music()
    art = _artwork()
    img = tmp_path / "abc123.jpg"
    img.write_bytes(b"x")
    out.update(np, art, img)
    payload = out._get_payload()
    assert payload["image"] == f"/image/current?v={img.stem}"
    assert payload["art_label"] == "Album art"


# ---------------------------------------------------------------------------
# _push
# ---------------------------------------------------------------------------

def test_push_sends_json_to_all_clients():
    out = _output()
    conn_a = _FakeConn()
    conn_b = _FakeConn()
    out._clients = {conn_a, conn_b}

    out._push({"state": "playing"})

    assert len(conn_a.sent) == 1
    assert json.loads(conn_a.sent[0]) == {"state": "playing"}
    assert len(conn_b.sent) == 1


def test_push_removes_dead_clients():
    out = _output()
    live = _FakeConn()
    dead = _FakeConn()
    dead.alive = False
    out._clients = {live, dead}

    out._push({"state": "idle"})

    assert live in out._clients
    assert dead not in out._clients


def test_push_with_no_clients_is_noop():
    out = _output()
    out._push({"state": "idle"})  # should not raise


# ---------------------------------------------------------------------------
# update / on_new_item / on_idle trigger _push
# ---------------------------------------------------------------------------

def test_update_pushes_payload(tmp_path):
    out = _output()
    conn = _FakeConn()
    out._clients = {conn}
    img = tmp_path / "xyz.jpg"
    img.write_bytes(b"x")

    out.update(_music(), _artwork(), img)

    assert len(conn.sent) == 1
    payload = json.loads(conn.sent[0])
    assert payload["title"] == "Bohemian Rhapsody"
    assert "image" in payload


def test_on_new_item_pushes_metadata_without_image():
    out = _output()
    conn = _FakeConn()
    out._clients = {conn}

    out.on_new_item(_music(), MagicMock())

    assert len(conn.sent) == 1
    payload = json.loads(conn.sent[0])
    assert payload["title"] == "Bohemian Rhapsody"
    assert "image" not in payload


def test_on_idle_pushes_empty_payload():
    out = _output()
    conn = _FakeConn()
    out._clients = {conn}

    out.on_idle()

    assert len(conn.sent) == 1
    assert json.loads(conn.sent[0]) == {}


def test_on_idle_clears_state():
    out = _output()
    out.on_new_item(_music(), MagicMock())
    out.on_idle()
    assert out._get_payload() == {}


# ---------------------------------------------------------------------------
# Sequence: on_new_item followed by update
# ---------------------------------------------------------------------------

def test_update_after_on_new_item_adds_image(tmp_path):
    out = _output()
    conn = _FakeConn()
    out._clients = {conn}
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")

    out.on_new_item(_music(), MagicMock())   # push 1: no image
    out.update(_music(), _artwork(), img)    # push 2: with image

    assert len(conn.sent) == 2
    first = json.loads(conn.sent[0])
    second = json.loads(conn.sent[1])
    assert "image" not in first
    assert "image" in second


# ---------------------------------------------------------------------------
# /health endpoint
# ---------------------------------------------------------------------------

def test_health_returns_starting_when_no_provider():
    out = _output()
    client = out.app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "starting"


def test_health_calls_provider_and_returns_json():
    out = _output()
    out.set_health_provider(lambda: {"status": "ok", "uptime_seconds": 42.0})
    client = out.app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["uptime_seconds"] == 42.0


def test_health_provider_can_be_replaced():
    out = _output()
    out.set_health_provider(lambda: {"status": "old"})
    out.set_health_provider(lambda: {"status": "new"})
    client = out.app.test_client()
    data = client.get("/health").get_json()
    assert data["status"] == "new"


def test_health_content_type_is_json():
    out = _output()
    out.set_health_provider(lambda: {"status": "ok"})
    client = out.app.test_client()
    resp = client.get("/health")
    assert "application/json" in resp.content_type
