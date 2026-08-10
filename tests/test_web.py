"""Tests for the WebOutput push logic."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from mediainfo.config import WebConfig
from mediainfo.models import Artwork, NowPlaying


def _config(**kwargs):
    return WebConfig(enabled=True, **kwargs)


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


# Suppress the real _rotate_clients_loop background thread (still started
# in __init__, unlike the old Flask server thread this output no longer
# owns) for all tests in this module - it loops forever otherwise.
@pytest.fixture(autouse=True)
def no_server(monkeypatch):
    monkeypatch.setattr("threading.Thread.start", lambda self: None)


def _output(config=None, rotation_interval_seconds=30):
    from mediainfo.outputs.web import WebOutput

    return WebOutput(config or _config(), rotation_interval_seconds)


def _client(out, url_prefix=""):
    """Register out's blueprint on a throwaway local Flask app and return
    a test client against it - see tests/test_nest_hub.py for the harness
    pattern (H1, see docs/architecture-usability-review-2026-07.md). Built
    as Flask("mediainfo.outputs.web"), not Flask(__name__), so the real
    mediainfo/outputs/templates/ directory resolves (see tests/test_feeds.py
    for why). sock=None (the default build_http_blueprint() argument) skips
    /ws registration - every test here that exercises WebSocket behavior
    does so via _connect()'s _FakeConn simulation, not a real socket
    handshake (Flask's test client can't hijack one - see
    mediainfo/outputs/http_server.py's module docstring for why /ws needs a
    real server at all).
    """
    app = Flask("mediainfo.outputs.web")
    app.register_blueprint(out.build_http_blueprint(url_prefix), url_prefix=url_prefix or None)
    return app.test_client()


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


def test_payload_includes_playback_position_when_reported():
    out = _output()
    np = _music()
    np.position_seconds = 42.5
    np.duration_seconds = 180.0
    out.on_new_item(np, MagicMock())
    payload = out._get_payload()
    assert payload["position_seconds"] == 42.5
    assert payload["duration_seconds"] == 180.0


def test_payload_omits_playback_position_when_unknown():
    # position/duration default to None ("unknown", not "at the start").
    out = _output()
    out.on_new_item(_music(), MagicMock())
    payload = out._get_payload()
    assert "position_seconds" not in payload
    assert "duration_seconds" not in payload


def test_personalized_payload_includes_playback_position():
    out = _output()
    np = _music()
    np.position_seconds = 10.0
    np.duration_seconds = 60.0
    out.on_new_item(np, MagicMock())
    conn = _connect(out)
    payload = out._personalized_payload(conn)
    assert payload["position_seconds"] == 10.0
    assert payload["duration_seconds"] == 60.0


def test_index_page_has_progress_bar():
    out = _output()
    body = _client(out).get("/").data.decode()
    assert 'id="progress"' in body


def test_index_page_stale_timeout_scales_with_rotation_interval():
    # A short configured rotation interval shouldn't shrink the reload
    # watchdog below its 90s floor - see the STALE_TIMEOUT_MS comment in
    # web/index.html.
    out = _output(rotation_interval_seconds=10)
    body = _client(out).get("/").data.decode()
    assert "Math.max(90000, 10 * 3000)" in body


def test_index_page_stale_timeout_uses_configured_interval_when_longer():
    out = _output(rotation_interval_seconds=300)
    body = _client(out).get("/").data.decode()
    assert "Math.max(90000, 300 * 3000)" in body


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

    out.on_new_item(_music(), cache)  # push 1: no image (pool still empty)
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


def test_personalized_payload_falls_through_pool_when_first_pick_fails(tmp_path):
    # A client's rotation position can land on an image the cache rejects
    # (e.g. below the minimum size) or fails to download - the payload
    # should fall through to the next image in that client's own rotation
    # order rather than coming back with no image at all.
    out = _output()
    images = [_art("a"), _art("b"), _art("c")]
    out._cache = _cache_for(tmp_path, images)
    # "a" fails to resolve; everything else succeeds.
    out._cache.get_path = lambda artwork, **kwargs: (
        None if artwork.label == "a" else tmp_path / f"{artwork.label}.jpg"
    )
    conn = _connect(out)

    with patch("mediainfo.outputs.web.random.shuffle", side_effect=lambda lst: None):
        out.update(_music(images=images), images[0], tmp_path / "a.jpg")
    out._client_rotation[conn].position = 0  # lands on "a", the rejected one

    payload = out._personalized_payload(conn)

    assert payload["art_label"] == "b"
    assert "image" in payload


def test_personalized_payload_has_no_image_when_every_candidate_fails(tmp_path):
    out = _output()
    images = [_art("a"), _art("b")]
    out._cache = _cache_for(tmp_path, images)
    out._cache.get_path = lambda artwork, **kwargs: None  # every candidate rejected
    conn = _connect(out)

    with out._lock:
        out._now_playing = _music(images=images)

    payload = out._personalized_payload(conn)

    assert "image" not in payload
    assert "art_label" not in payload


def test_resolve_artwork_path_passes_through_tier(tmp_path):
    out = _output()
    art = _art("cover")
    path = tmp_path / "cover.jpg"
    path.write_bytes(b"x")
    cache = MagicMock(get_path=MagicMock(return_value=path), get_transformed_path=lambda p, _: p)

    out._resolve_artwork_path(cache, art, tier="music")

    cache.get_path.assert_called_once_with(art, tier="music")


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


class _StopLoop(Exception):
    """Sentinel used to break out of the infinite _rotate_clients_loop in
    tests once we've proven it survived a prior exception."""


def test_rotate_clients_loop_survives_unexpected_exception(monkeypatch):
    # _rotate_clients_loop's except clause necessarily catches *any*
    # exception (that's the fix), so the loop can't be stopped by raising
    # through _rotate_clients_once - the sleep call (outside the
    # try/except) is the only place this test can inject a way out.
    out = _output()
    calls = []
    sleep_calls = []

    def _boom():
        calls.append(1)
        raise RuntimeError("boom")

    def _fake_sleep(_seconds):
        sleep_calls.append(1)
        if len(sleep_calls) >= 2:
            raise _StopLoop()

    monkeypatch.setattr(out, "_rotate_clients_once", _boom)
    monkeypatch.setattr("mediainfo.outputs.web.time.sleep", _fake_sleep)

    with pytest.raises(_StopLoop):
        out._rotate_clients_loop()

    # The loop survived the first RuntimeError and made it back around to
    # sleep() a second time - proof the thread doesn't die on an
    # unexpected exception.
    assert len(calls) == 1
    assert len(sleep_calls) == 2


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

    resp = _client(out).get("/image/current?v=abc")

    assert resp.status_code == 200
    assert resp.data == b"image-bytes"


def test_image_current_falls_back_to_global_pick_for_unknown_v(tmp_path):
    out = _output()
    img = tmp_path / "fallback.jpg"
    img.write_bytes(b"fallback-bytes")
    out._image_path = img

    resp = _client(out).get("/image/current?v=does-not-exist")

    assert resp.status_code == 200
    assert resp.data == b"fallback-bytes"


def test_image_current_404_when_nothing_available():
    out = _output()
    resp = _client(out).get("/image/current")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /health endpoint
# ---------------------------------------------------------------------------


def test_health_returns_starting_when_no_provider():
    out = _output()
    client = _client(out)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "starting"


def test_health_calls_provider_and_returns_json():
    out = _output()
    out.set_health_provider(lambda: {"status": "ok", "uptime_seconds": 42.0})
    client = _client(out)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["uptime_seconds"] == 42.0


def test_health_provider_can_be_replaced():
    out = _output()
    out.set_health_provider(lambda: {"status": "old"})
    out.set_health_provider(lambda: {"status": "new"})
    client = _client(out)
    data = client.get("/health").get_json()
    assert data["status"] == "new"


def test_health_content_type_is_json():
    out = _output()
    out.set_health_provider(lambda: {"status": "ok"})
    client = _client(out)
    resp = client.get("/health")
    assert "application/json" in resp.content_type


# ---------------------------------------------------------------------------
# attach() - see mediainfo.app_services.AppServices
# ---------------------------------------------------------------------------


def test_attach_wires_health_provider_and_history():
    from mediainfo.app_services import AppServices

    out = _output()

    def provider():
        return {"status": "ok"}

    history = MagicMock()

    out.attach(AppServices(health_provider=provider, history=history))

    client = _client(out)
    assert client.get("/health").get_json()["status"] == "ok"
    assert out._history is history


def test_attach_passes_through_none_history():
    from mediainfo.app_services import AppServices

    out = _output()
    out.attach(AppServices(health_provider=lambda: {"status": "ok"}, history=None))
    assert out._history is None


# ---------------------------------------------------------------------------
# Image transitions
# ---------------------------------------------------------------------------


def test_index_page_includes_all_transitions_by_default():
    out = _output()
    body = _client(out).get("/").data.decode()
    assert "t-slide-left" in body
    assert "prepareForTransition" in body


def test_index_page_excludes_configured_transitions():
    out = _output(_config(transition_exclude=["slide-left", "zoom"]))
    body = _client(out).get("/").data.decode()
    variants_section = body.split("TRANSITION_VARIANTS = ")[1].split(";")[0]
    assert "t-slide-left" not in variants_section
    assert "t-zoom" not in variants_section


# Optional auth: no longer tested per-output - install_auth() is called
# once, centrally, by SharedHttpServer (mediainfo/outputs/http_server.py),
# not by WebOutput itself. See tests/test_web_auth.py (the private/public
# address + Basic Auth logic itself) and tests/test_http_server.py (the
# CSRF-header guard, wired the same way).


# ---------------------------------------------------------------------------
# Playback history page (/history, /api/history, /history/image/<id>)
# ---------------------------------------------------------------------------


def _history_store(tmp_path):
    from mediainfo.stores.history import PlaybackHistory

    return PlaybackHistory(str(tmp_path / "history.db"))


def test_history_api_reports_disabled_without_store():
    out = _output()
    resp = _client(out).get("/api/history")
    assert resp.get_json() == {"enabled": False, "items": []}


def test_history_api_lists_entries(tmp_path):
    store = _history_store(tmp_path)
    store.record(_music())
    out = _output()
    out.set_history(store)

    data = _client(out).get("/api/history").get_json()
    assert data["enabled"] is True
    assert data["items"][0]["title"] == "Bohemian Rhapsody"


def test_history_page_served():
    out = _output()
    body = _client(out).get("/history").data.decode()
    assert "Recently played" in body


def test_history_image_resolved_through_cache(tmp_path):
    store = _history_store(tmp_path)
    store.record(_music(images=[Artwork(url="http://x/cover.jpg")]))
    entry_id = store.list()[0]["id"]

    img = tmp_path / "cover.jpg"
    img.write_bytes(b"cover-bytes")
    cache = MagicMock()
    cache.get_path.return_value = img

    from mediainfo.outputs.web import WebOutput

    out = WebOutput(_config(), 30, cache)
    out.set_history(store)

    resp = _client(out).get(f"/history/image/{entry_id}")
    assert resp.status_code == 200
    assert resp.data == b"cover-bytes"
    # music entry -> music cache tier (never purged)
    assert cache.get_path.call_args.kwargs["tier"] == "music"


def test_history_image_404_for_unknown_entry(tmp_path):
    out = _output()
    out.set_history(_history_store(tmp_path))
    assert _client(out).get("/history/image/999").status_code == 404


def test_show_wordclouds_is_enabled():
    from mediainfo.outputs.web import WebOutput

    assert WebOutput.show_wordclouds is True
