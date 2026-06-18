"""Tests for the WebOutput push logic."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mediainfo.config import WebConfig
from mediainfo.models import Artwork, NowPlaying


def _config(**kwargs):
    return WebConfig(enabled=True, host="127.0.0.1", port=8090, **kwargs)


def _music(title="Bohemian Rhapsody", artist="Queen", images=None):
    return NowPlaying(
        source="kodi",
        media_type="music",
        title=title,
        subtitle=artist,
        images=images if images is not None else [],
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


def _output(config=None, rotation_interval_seconds=30):
    from mediainfo.outputs.web import WebOutput
    return WebOutput(config or _config(), rotation_interval_seconds)


def _connect(out) -> "_FakeConn":
    """Simulate a real /ws connection: register the client and assign it a
    rotation state, the same as the real route handler does."""
    conn = _FakeConn()
    with out._clients_lock:
        out._clients.add(conn)
        out._assign_client_rotation(conn)
    return conn


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
    conn = _connect(out)
    img = tmp_path / "xyz.jpg"
    img.write_bytes(b"x")
    art = _artwork()
    out._cache = MagicMock(get_path=lambda *a, **k: img, get_transformed_path=lambda p, _: p)

    out.update(_music(images=[art]), art, img)

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
    conn = _connect(out)
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")
    art = _artwork()
    cache = MagicMock(get_path=lambda *a, **k: img, get_transformed_path=lambda p, _: p)

    out.on_new_item(_music(), cache)         # push 1: no image (pool still empty)
    out.update(_music(images=[art]), art, img)  # push 2: pool now has an image

    assert len(conn.sent) == 2
    first = json.loads(conn.sent[0])
    second = json.loads(conn.sent[1])
    assert "image" not in first
    assert "image" in second


# ---------------------------------------------------------------------------
# Per-client rotation (multiple screens sharing one port)
# ---------------------------------------------------------------------------

def _art(label):
    return Artwork(url=f"https://example.com/{label}.jpg", label=label)


def _cache_for(tmp_path, images):
    """A fake ImageCache that maps each artwork to its own distinct file."""
    paths = {}
    for art in images:
        path = tmp_path / f"{art.label}.jpg"
        path.write_bytes(b"x")
        paths[art.url] = path
    return MagicMock(
        get_path=lambda artwork, **kwargs: paths.get(artwork.url),
        get_transformed_path=lambda p, _: p,
    )


def test_each_client_gets_a_distinct_starting_image(tmp_path):
    out = _output()
    images = [_art("a"), _art("b"), _art("c")]
    out._cache = _cache_for(tmp_path, images)
    conn_x = _connect(out)
    conn_y = _connect(out)

    with patch("mediainfo.outputs.web.random.shuffle", side_effect=lambda lst: None):
        out.update(_music(images=images), images[0], tmp_path / "a.jpg")

    payload_x = json.loads(conn_x.sent[-1])
    payload_y = json.loads(conn_y.sent[-1])
    assert payload_x["art_label"] != payload_y["art_label"]


def test_client_connecting_after_pool_established_gets_assigned_rotation(tmp_path):
    out = _output()
    images = [_art("a"), _art("b")]
    out._cache = _cache_for(tmp_path, images)
    out.update(_music(images=images), images[0], tmp_path / "a.jpg")

    conn = _connect(out)

    assert conn in out._client_rotation


def test_update_with_unchanged_pool_does_not_reset_client_position(tmp_path):
    out = _output()
    images = [_art("a"), _art("b")]
    out._cache = _cache_for(tmp_path, images)
    conn = _connect(out)
    out.update(_music(images=images), images[0], tmp_path / "a.jpg")

    state_before = out._client_rotation[conn]
    state_before.position = 1  # simulate having already rotated once

    out.update(_music(images=images), images[1], tmp_path / "b.jpg")  # same pool

    assert out._client_rotation[conn] is state_before
    assert out._client_rotation[conn].position == 1


def test_rotate_clients_once_advances_due_clients(tmp_path):
    out = _output(rotation_interval_seconds=10)
    images = [_art("a"), _art("b"), _art("c")]
    out._cache = _cache_for(tmp_path, images)
    conn = _connect(out)
    out.update(_music(images=images), images[0], tmp_path / "a.jpg")

    state = out._client_rotation[conn]
    state.next_due = time.monotonic() - 1  # force due now
    start_position = state.position

    out._rotate_clients_once()

    assert out._client_rotation[conn].position == (start_position + 1) % len(images)


def test_rotate_clients_once_skips_clients_not_yet_due(tmp_path):
    out = _output(rotation_interval_seconds=300)
    images = [_art("a"), _art("b")]
    out._cache = _cache_for(tmp_path, images)
    conn = _connect(out)
    out.update(_music(images=images), images[0], tmp_path / "a.jpg")
    out._client_rotation[conn].next_due = time.monotonic() + 300  # far in the future

    sent_before = len(conn.sent)
    out._rotate_clients_once()

    assert len(conn.sent) == sent_before  # no push, not due yet


def test_idle_wallpapers_are_personalized_per_client(tmp_path):
    out = _output()
    images = [_art("a"), _art("b")]
    out._cache = _cache_for(tmp_path, images)
    idle_now_playing = NowPlaying(
        source="idle", media_type="wallpaper", title="", subtitle="", images=images
    )
    conn_x = _connect(out)
    conn_y = _connect(out)

    with patch("mediainfo.outputs.web.random.shuffle", side_effect=lambda lst: None):
        out.update(idle_now_playing, images[0], tmp_path / "a.jpg")

    payload_x = json.loads(conn_x.sent[-1])
    payload_y = json.loads(conn_y.sent[-1])
    assert payload_x["art_label"] != payload_y["art_label"]


def test_disconnect_removes_client_rotation_state(tmp_path):
    out = _output()
    images = [_art("a")]
    out._cache = _cache_for(tmp_path, images)
    conn = _connect(out)
    out.update(_music(images=images), images[0], tmp_path / "a.jpg")
    assert conn in out._client_rotation

    with out._clients_lock:
        out._clients.discard(conn)
        out._client_rotation.pop(conn, None)

    assert conn not in out._client_rotation


# ---------------------------------------------------------------------------
# /image/current ?v= lookup
# ---------------------------------------------------------------------------

def test_image_current_serves_file_for_known_v(tmp_path):
    out = _output()
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"image-bytes")
    out._known_images["abc"] = img

    resp = out.app.test_client().get("/image/current?v=abc")

    assert resp.status_code == 200
    assert resp.data == b"image-bytes"


def test_image_current_falls_back_to_global_pick_for_unknown_v(tmp_path):
    out = _output()
    img = tmp_path / "fallback.jpg"
    img.write_bytes(b"fallback-bytes")
    out._image_path = img

    resp = out.app.test_client().get("/image/current?v=does-not-exist")

    assert resp.status_code == 200
    assert resp.data == b"fallback-bytes"


def test_image_current_404_when_nothing_available():
    out = _output()
    resp = out.app.test_client().get("/image/current")
    assert resp.status_code == 404


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
