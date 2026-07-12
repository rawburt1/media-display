"""Tests for the Flask HTTP server."""

from unittest.mock import MagicMock

import pytest

from vinyl_recognizer.server import create_app


_TRACK = {
    "title": "Comfortably Numb",
    "artist": "Pink Floyd",
    "album": "The Wall",
    "artwork_url": "",
}
_WAV = b"RIFF\x00\x00\x00\x00WAVEfmt "


@pytest.fixture
def service():
    svc = MagicMock()
    svc.get_now_playing.return_value = {}
    svc.recognize.return_value = None
    return svc


@pytest.fixture
def client(service):
    app = create_app(service)
    app.config["TESTING"] = True
    return app.test_client(), service


def test_now_playing_returns_empty_when_nothing_playing(client):
    c, service = client
    service.get_now_playing.return_value = {}
    resp = c.get("/now-playing")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_now_playing_returns_current_track(client):
    c, service = client
    service.get_now_playing.return_value = _TRACK
    resp = c.get("/now-playing")
    assert resp.get_json()["title"] == "Comfortably Numb"


def test_recognize_returns_empty_on_no_match(client):
    c, service = client
    service.recognize.return_value = None
    resp = c.post("/recognize", data=_WAV, content_type="audio/wav")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_recognize_returns_track_on_match(client):
    c, service = client
    service.recognize.return_value = _TRACK
    resp = c.post("/recognize", data=_WAV, content_type="audio/wav")
    assert resp.status_code == 200
    assert resp.get_json()["title"] == "Comfortably Numb"
    assert resp.get_json()["artist"] == "Pink Floyd"


def test_recognize_passes_wav_bytes_to_service(client):
    c, service = client
    c.post("/recognize", data=_WAV, content_type="audio/wav")
    service.recognize.assert_called_once_with(_WAV)


def test_recognize_returns_400_when_no_body(client):
    c, _ = client
    resp = c.post("/recognize", data=b"", content_type="audio/wav")
    assert resp.status_code == 400
    assert "error" in resp.get_json()
