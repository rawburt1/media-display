"""Tests for the ThemesOutput push logic - see mediainfo/outputs/themes.py.

Mirrors tests/test_info.py's structure (ThemesOutput is architecturally a
broadcast-to-all-clients sibling of InfoOutput, not WebOutput's independent
per-client rotation), plus theme-aggregation tests using a fake DisplayTheme
registered via monkeypatched THEME_CLASSES/THEMES_CONFIG_TYPES (isolates the
aggregation plumbing from any one real theme's own behavior - see
test_color_palette_theme.py for that, and the real end-to-end check at the
bottom of this file).
"""

import json
from unittest.mock import MagicMock

import pydantic
import pytest

from mediainfo.config import ThemesConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult


def _config(**kwargs):
    return ThemesConfig(enabled=True, host="127.0.0.1", port=8097, **kwargs)


def _music(title="Bohemian Rhapsody", artist="Queen"):
    return NowPlaying(source="kodi", media_type="music", title=title, subtitle=artist, images=[])


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
    from mediainfo.outputs.themes import ThemesOutput
    return ThemesOutput(config or _config())


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
    assert "image" not in payload


def test_payload_when_playing_with_image(tmp_path):
    out = _output()
    img = tmp_path / "abc123.jpg"
    img.write_bytes(b"x")
    out.update(_music(), _artwork(), img)
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


def test_index_page_serves():
    out = _output()
    resp = out.app.test_client().get("/")
    assert resp.status_code == 200
    assert b"themeHandlers" in resp.data


def test_image_endpoint_serves_by_stem(tmp_path):
    out = _output()
    img = tmp_path / "abc123.jpg"
    img.write_bytes(b"fake-bytes")
    out.update(_music(), _artwork(), img)

    resp = out.app.test_client().get("/image/current?v=abc123")
    assert resp.status_code == 200
    assert resp.data == b"fake-bytes"


def test_image_endpoint_404_when_nothing_playing():
    out = _output()
    resp = out.app.test_client().get("/image/current")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# _push / broadcast
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


def test_on_idle_pushes_empty_payload():
    out = _output()
    conn = _FakeConn()
    out._clients = {conn}

    out.on_idle()

    assert json.loads(conn.sent[0]) == {}


# ---------------------------------------------------------------------------
# No themes registered yet (Phase 0) - a themes output behaves like a bare
# artwork+metadata display.
# ---------------------------------------------------------------------------

def test_no_themes_registered_by_default():
    out = _output()
    assert out._themes == []


def test_payload_has_no_themes_key_when_none_enabled(tmp_path):
    out = _output()
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")
    out.update(_music(), _artwork(), img)
    assert "themes" not in out._get_payload()


# ---------------------------------------------------------------------------
# Theme aggregation - using a fake DisplayTheme, since none ships yet.
# ---------------------------------------------------------------------------

@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class _FakeGlowConfig:
    enabled: bool = False
    intensity: float = 0.5


class _FakeGlowTheme(DisplayTheme):
    name = "glow"

    def client_assets(self, config):
        return ThemeClientAssets(css=".glow { color: red; }", js="console.log('glow');")

    def prepare(self, now_playing, artwork, image_path, cache, media_data, config):
        return ThemeRenderResult(extra_payload={"intensity": config.intensity})


@pytest.fixture
def fake_glow_theme(monkeypatch):
    monkeypatch.setattr(
        "mediainfo.config.themes.THEMES_CONFIG_TYPES", {"glow": _FakeGlowConfig},
    )
    monkeypatch.setattr("mediainfo.registries.THEME_CLASSES", {"glow": _FakeGlowTheme})


def test_enabled_theme_is_instantiated(fake_glow_theme):
    out = _output(_config(themes={"glow": {"enabled": True, "intensity": 0.9}}))
    assert len(out._themes) == 1
    assert out._themes[0].name == "glow"


def test_disabled_theme_is_not_instantiated(fake_glow_theme):
    out = _output(_config(themes={"glow": {"enabled": False}}))
    assert out._themes == []


def test_theme_client_assets_are_aggregated(fake_glow_theme):
    out = _output(_config(themes={"glow": {"enabled": True}}))
    assert ".glow" in out._theme_css
    assert "console.log" in out._theme_js


def test_theme_client_assets_injected_into_page(fake_glow_theme):
    out = _output(_config(themes={"glow": {"enabled": True}}))
    body = out.app.test_client().get("/").data.decode()
    assert ".glow { color: red; }" in body
    assert "console.log('glow');" in body


def test_theme_prepare_result_merged_into_payload(fake_glow_theme, tmp_path):
    out = _output(_config(themes={"glow": {"enabled": True, "intensity": 0.9}}))
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")

    out.on_new_item(_music(), cache=MagicMock())
    out.update(_music(), _artwork(), img)

    payload = out._get_payload()
    assert payload["themes"]["glow"] == {"intensity": 0.9}


def test_theme_prepare_not_called_without_cache(fake_glow_theme, tmp_path):
    out = _output(_config(themes={"glow": {"enabled": True}}))
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")

    # update() without a prior on_new_item() means self._cache is still None.
    out.update(_music(), _artwork(), img)

    assert "themes" not in out._get_payload()


class _RaisingTheme(DisplayTheme):
    name = "glow"

    def prepare(self, now_playing, artwork, image_path, cache, media_data, config):
        raise RuntimeError("boom")


def test_theme_prepare_exception_is_caught_not_raised(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "mediainfo.config.themes.THEMES_CONFIG_TYPES", {"glow": _FakeGlowConfig},
    )
    monkeypatch.setattr("mediainfo.registries.THEME_CLASSES", {"glow": _RaisingTheme})
    out = _output(_config(themes={"glow": {"enabled": True}}))
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")

    out.on_new_item(_music(), cache=MagicMock())
    out.update(_music(), _artwork(), img)  # must not raise

    assert "themes" not in out._get_payload()


def test_unknown_theme_name_is_skipped(caplog):
    out = _output(_config(themes={"nonexistent": {"enabled": True}}))
    assert out._themes == []
    assert "nonexistent" in caplog.text


class _BakingTheme(DisplayTheme):
    name = "glow"

    def prepare(self, now_playing, artwork, image_path, cache, media_data, config):
        derived = image_path.parent / "derived.png"
        derived.write_bytes(b"derived-bytes")
        return ThemeRenderResult(derived_image_path=derived)


def test_derived_theme_image_is_servable(monkeypatch, tmp_path):
    """A theme that bakes a derived composite image should have it
    registered in _known_images so /image/current?v=<stem> can serve it -
    the bug this test guards against: only tracking the main image_path
    and silently 404ing on any theme-derived image URL."""
    monkeypatch.setattr(
        "mediainfo.config.themes.THEMES_CONFIG_TYPES", {"glow": _FakeGlowConfig},
    )
    monkeypatch.setattr("mediainfo.registries.THEME_CLASSES", {"glow": _BakingTheme})

    out = _output(_config(themes={"glow": {"enabled": True}}))
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")
    out.on_new_item(_music(), cache=MagicMock())
    out.update(_music(), _artwork(), img)

    payload = out._get_payload()
    image_url = payload["themes"]["glow"]["image"]
    v = image_url.split("v=")[1]

    resp = out.app.test_client().get(f"/image/current?v={v}")
    assert resp.status_code == 200
    assert resp.data == b"derived-bytes"


# ---------------------------------------------------------------------------
# Real end-to-end check with the actual Color Palette theme (no fakes/
# monkeypatching - this is genuinely registered in registries.THEME_CLASSES
# and mediainfo.config.themes.THEMES_CONFIG_TYPES), proving the whole path
# from config through to the rendered page works for a real theme, not just
# the aggregation plumbing exercised above.
# ---------------------------------------------------------------------------

def test_real_color_palette_theme_end_to_end(tmp_path):
    from PIL import Image

    img_path = tmp_path / "art.png"
    Image.new("RGB", (32, 32), (10, 20, 30)).save(img_path)

    out = _output(_config(themes={"color_palette": {"enabled": True, "swatch_count": 1}}))
    assert out._themes[0].name == "color_palette"

    out.on_new_item(_music(), cache=MagicMock())
    out.update(_music(), _artwork(), img_path)

    payload = out._get_payload()
    assert payload["themes"]["color_palette"]["colors"] == ["#0a141e"]

    body = out.app.test_client().get("/").data.decode()
    # Exactly once, not just "in" - guards against a template placeholder
    # accidentally sitting inside a comment (see the regression test
    # below), which would duplicate the injected content and run it out
    # of order relative to window.themeHandlers' own initialization.
    assert body.count("window.themeHandlers.color_palette = function") == 1
    assert "theme-color-palette" in body


def test_real_blurred_background_theme_end_to_end(tmp_path):
    from PIL import Image

    from mediainfo.cache import ImageCache

    img_path = tmp_path / "art.jpg"
    Image.new("RGB", (200, 200), (200, 50, 50)).save(img_path)
    cache = ImageCache(tmp_path / "cache")

    out = _output(_config(themes={"blurred_background": {"enabled": True}}))
    assert out._themes[0].name == "blurred_background"

    out.on_new_item(_music(), cache=cache)
    out.update(_music(), _artwork(), img_path)

    payload = out._get_payload()
    image_url = payload["themes"]["blurred_background"]["image"]
    v = image_url.split("v=")[1]

    resp = out.app.test_client().get(f"/image/current?v={v}")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"

    body = out.app.test_client().get("/").data.decode()
    assert body.count("window.themeHandlers.blurred_background = function") == 1


def test_real_themes_page_has_valid_script_no_stray_placeholder_text(tmp_path):
    """Regression test: templates/themes/index.html's own prose comments
    once contained the literal `{{ theme_css }}`/`{{ theme_js }}` tokens as
    descriptive text (e.g. "via {{ theme_css }}"), which Jinja rendered
    too - injecting a theme's CSS/JS in the middle of an unrelated comment,
    corrupting it and running theme JS before window.themeHandlers was even
    initialized. Renders the real page with both real themes enabled and
    checks the handler registrations land exactly once, in a script block
    that starts after window.themeHandlers's own init - not just "somewhere
    in the page"."""
    img_path = tmp_path / "art.jpg"
    from PIL import Image

    from mediainfo.cache import ImageCache

    Image.new("RGB", (64, 64), (80, 120, 160)).save(img_path)
    cache = ImageCache(tmp_path / "cache")

    out = _output(_config(themes={
        "color_palette": {"enabled": True},
        "blurred_background": {"enabled": True},
    }))
    out.on_new_item(_music(), cache=cache)
    out.update(_music(), _artwork(), img_path)

    body = out.app.test_client().get("/").data.decode()
    assert body.count("window.themeHandlers.color_palette = function") == 1
    assert body.count("window.themeHandlers.blurred_background = function") == 1
    assert "{{ theme_css }}" not in body
    assert "{{ theme_js }}" not in body

    init_pos = body.index("window.themeHandlers = window.themeHandlers || {}")
    palette_pos = body.index("window.themeHandlers.color_palette = function")
    bg_pos = body.index("window.themeHandlers.blurred_background = function")
    assert init_pos < palette_pos
    assert init_pos < bg_pos


def test_real_word_cloud_theme_end_to_end_music(tmp_path):
    from mediainfo.media_data_store import MediaDataStore

    wc_path = tmp_path / "wc.png"
    wc_path.write_bytes(b"fake-wordcloud-png")
    media_data = MagicMock(spec=MediaDataStore)
    media_data.get_track_wordcloud.return_value = wc_path

    out = _output(_config(themes={"word_cloud": {"enabled": True}}))
    out.set_media_data_store(media_data)
    assert out._themes[0].name == "word_cloud"

    song = NowPlaying(
        source="kodi", media_type="music", title="Bohemian Rhapsody", subtitle="Queen", album="A Night at the Opera",
    )
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")
    out.on_new_item(song, cache=MagicMock())
    out.update(song, _artwork(), img_path)

    payload = out._get_payload()
    image_url = payload["themes"]["word_cloud"]["image"]
    v = image_url.split("v=")[1]

    resp = out.app.test_client().get(f"/image/current?v={v}")
    assert resp.status_code == 200
    assert resp.data == b"fake-wordcloud-png"


def test_real_word_cloud_theme_end_to_end_movie(tmp_path):
    from PIL import Image

    from mediainfo.cache import ImageCache

    img_path = tmp_path / "poster.jpg"
    Image.new("RGB", (64, 64), (30, 60, 90)).save(img_path)
    cache = ImageCache(tmp_path / "cache")

    out = _output(_config(themes={"word_cloud": {"enabled": True}}))
    movie = NowPlaying(source="kodi", media_type="movie", title="Alien", summary="A crew in deep space.")

    out.on_new_item(movie, cache=cache)
    out.update(movie, _artwork(), img_path)

    payload = out._get_payload()
    image_url = payload["themes"]["word_cloud"]["image"]
    v = image_url.split("v=")[1]

    resp = out.app.test_client().get(f"/image/current?v={v}")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"

    body = out.app.test_client().get("/").data.decode()
    assert "window.themeHandlers.word_cloud" in body


def test_real_glow_theme_end_to_end(tmp_path):
    from PIL import Image

    img_path = tmp_path / "art.png"
    Image.new("RGB", (32, 32), (200, 50, 50)).save(img_path)

    out = _output(_config(themes={"glow": {"enabled": True, "intensity": 0.8}}))
    assert out._themes[0].name == "glow"

    out.on_new_item(_music(), cache=MagicMock())
    out.update(_music(), _artwork(), img_path)

    payload = out._get_payload()
    assert payload["themes"]["glow"]["color"] == "#c83232"

    body = out.app.test_client().get("/").data.decode()
    assert "window.themeHandlers.glow" in body
    assert "theme-glow" in body


def test_real_ken_burns_theme_end_to_end(tmp_path):
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")

    out = _output(_config(themes={"ken_burns": {"enabled": True, "duration_seconds": 15}}))
    assert out._themes[0].name == "ken_burns"

    out.on_new_item(_music(), cache=MagicMock())
    out.update(_music(), _artwork(), img_path)

    payload = out._get_payload()
    assert payload["themes"]["ken_burns"]["image"] == f"/image/current?v={img_path.stem}"

    body = out.app.test_client().get("/").data.decode()
    assert body.count("window.themeHandlers.ken_burns = function") == 1
    assert "15s" in body


def test_real_vinyl_theme_end_to_end_music(tmp_path):
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")

    out = _output(_config(themes={"vinyl": {"enabled": True, "rotation_seconds": 6}}))
    assert out._themes[0].name == "vinyl"

    out.on_new_item(_music(), cache=MagicMock())
    out.update(_music(), _artwork(), img_path)

    payload = out._get_payload()
    assert payload["themes"]["vinyl"]["image"] == f"/image/current?v={img_path.stem}"

    body = out.app.test_client().get("/").data.decode()
    assert body.count("window.themeHandlers.vinyl = function") == 1
    assert "6s" in body


def test_real_vinyl_theme_end_to_end_movie_produces_nothing(tmp_path):
    img_path = tmp_path / "poster.jpg"
    img_path.write_bytes(b"x")

    out = _output(_config(themes={"vinyl": {"enabled": True}}))
    movie = NowPlaying(source="kodi", media_type="movie", title="Alien")

    out.on_new_item(movie, cache=MagicMock())
    out.update(movie, _artwork(), img_path)

    payload = out._get_payload()
    assert "vinyl" not in payload.get("themes", {})
