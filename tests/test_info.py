"""Tests for the InfoOutput push logic."""

import json
from unittest.mock import MagicMock

import pytest

from mediainfo.config import InfoConfig
from mediainfo.models import Artwork, NowPlaying


def _config(**kwargs):
    return InfoConfig(enabled=True, host="127.0.0.1", port=8093, **kwargs)


def _music(title="Bohemian Rhapsody", artist="Queen", summary="", lyrics="", rating=None):
    return NowPlaying(
        source="kodi",
        media_type="music",
        title=title,
        subtitle=artist,
        summary=summary,
        lyrics=lyrics,
        rating=rating,
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


@pytest.fixture(autouse=True)
def no_server(monkeypatch):
    monkeypatch.setattr("threading.Thread.start", lambda self: None)


def _output(config=None):
    from mediainfo.outputs.info import InfoOutput
    return InfoOutput(config or _config())


# ---------------------------------------------------------------------------
# _get_payload
# ---------------------------------------------------------------------------

def test_payload_when_idle():
    out = _output()
    assert out._get_payload() == {}


def test_payload_when_playing_without_image():
    out = _output()
    out.on_new_item(_music(summary="A British rock band."), MagicMock())
    payload = out._get_payload()
    assert payload["title"] == "Bohemian Rhapsody"
    assert payload["subtitle"] == "Queen"
    assert payload["summary"] == "A British rock band."
    assert "image" not in payload


def test_payload_includes_lyrics_and_rating():
    out = _output()
    out.on_new_item(_music(lyrics="Is this the real life?", rating=8.5), MagicMock())
    payload = out._get_payload()
    assert payload["lyrics"] == "Is this the real life?"
    assert payload["rating"] == 8.5


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
# No default transforms (high-resolution by default)
# ---------------------------------------------------------------------------

def test_default_transform_pipeline_is_empty():
    out = _output()
    assert out.transform_pipeline == []


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

def test_index_page_served():
    out = _output()
    client = out.app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Now Playing" in resp.data


def test_now_playing_json_endpoint():
    out = _output()
    out.on_new_item(_music(summary="bio text"), MagicMock())
    client = out.app.test_client()
    resp = client.get("/api/now-playing")
    data = resp.get_json()
    assert data["summary"] == "bio text"


def test_current_image_404_when_none():
    out = _output()
    client = out.app.test_client()
    resp = client.get("/image/current")
    assert resp.status_code == 404
