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
from flask import Flask

from mediainfo.config import ThemesConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult


def _config(**kwargs):
    return ThemesConfig(enabled=True, **kwargs)


def _music(title="Bohemian Rhapsody", artist="Queen"):
    return NowPlaying(source="kodi", media_type="music", title=title, subtitle=artist, images=[])


def _movie(title="Inception"):
    return NowPlaying(source="kodi", media_type="movie", title=title, images=[])


def _wallpaper():
    # Matches orchestrator_idle.py's NowPlaying(..., media_type="wallpaper",
    # ...) construction for idle wallpapers - the "idle" media type in a
    # preset's `when` maps onto this internal value (see ThemesOutput's
    # _IDLE_MEDIA_TYPE_ALIAS).
    return NowPlaying(source="idle", media_type="wallpaper", title="", images=[])


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


def _client(out, url_prefix=""):
    """See tests/test_nest_hub.py for the harness pattern (H1, see
    docs/architecture-usability-review-2026-07.md). Built as
    Flask("mediainfo.outputs.themes") so templates/ resolves - see
    tests/test_feeds.py for why."""
    app = Flask("mediainfo.outputs.themes")
    app.register_blueprint(out.build_http_blueprint(url_prefix), url_prefix=url_prefix or None)
    return app.test_client()


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


def test_image_survives_caller_deleting_the_original_path(tmp_path):
    # Regression test: orchestrator_idle.py downloads idle wallpapers to a
    # temp file and deletes it immediately after update() returns (the
    # caller owns that file, not this output) - but _get_payload() can be
    # called again much later (a WebSocket client connecting, or
    # /api/now-playing being polled), fully decoupled from that update()
    # call. update() must keep its own copy so this doesn't crash/404.
    out = _output()
    img = tmp_path / "abc123.jpg"
    img.write_bytes(b"fake-bytes")
    out.update(_music(), _artwork(), img)

    img.unlink()  # simulate orchestrator_idle's immediate cleanup

    payload = out._get_payload()
    assert payload["image"] == "/image/current?v=abc123"
    resp = _client(out).get("/image/current?v=abc123")
    assert resp.status_code == 200
    assert resp.data == b"fake-bytes"


def test_second_update_replaces_and_cleans_up_the_owned_copy(tmp_path):
    out = _output()
    img1 = tmp_path / "img1.jpg"
    img1.write_bytes(b"first")
    out.update(_music(), _artwork(), img1)
    first_owned_path = out._owned_image_path
    assert first_owned_path.exists()

    img2 = tmp_path / "img2.jpg"
    img2.write_bytes(b"second")
    out.update(_music(), _artwork(), img2)

    assert not first_owned_path.exists()  # superseded copy cleaned up
    assert out._owned_image_path.read_bytes() == b"second"


def test_repushing_the_same_image_does_not_delete_it(tmp_path):
    # A periodic re-push of an unchanged item (see _maybe_rotate) copies
    # the same filename over itself - must not unlink the file it just
    # wrote (old_owned_path == stable_path in that case).
    out = _output()
    img = tmp_path / "abc123.jpg"
    img.write_bytes(b"fake-bytes")
    out.update(_music(), _artwork(), img)
    out.update(_music(), _artwork(), img)

    assert out._owned_image_path.exists()
    assert out._owned_image_path.read_bytes() == b"fake-bytes"


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
    resp = _client(out).get("/")
    assert resp.status_code == 200
    assert b"themeHandlers" in resp.data


def test_image_endpoint_serves_by_stem(tmp_path):
    out = _output()
    img = tmp_path / "abc123.jpg"
    img.write_bytes(b"fake-bytes")
    out.update(_music(), _artwork(), img)

    resp = _client(out).get("/image/current?v=abc123")
    assert resp.status_code == 200
    assert resp.data == b"fake-bytes"


def test_image_endpoint_404_when_nothing_playing():
    out = _output()
    resp = _client(out).get("/image/current")
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
        "mediainfo.config.themes.THEMES_CONFIG_TYPES",
        {"glow": _FakeGlowConfig},
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
    body = _client(out).get("/").data.decode()
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
        "mediainfo.config.themes.THEMES_CONFIG_TYPES",
        {"glow": _FakeGlowConfig},
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


# ---------------------------------------------------------------------------
# health_check() - aggregates each theme's own health_detail()
# ---------------------------------------------------------------------------


class _HealthyTheme(DisplayTheme):
    name = "glow"


class _DegradedTheme(DisplayTheme):
    name = "glow"

    def health_detail(self, config):
        return {"degraded": True, "reason": "something is off"}


def test_health_check_none_when_no_theme_reports_anything(monkeypatch):
    monkeypatch.setattr(
        "mediainfo.config.themes.THEMES_CONFIG_TYPES",
        {"glow": _FakeGlowConfig},
    )
    monkeypatch.setattr("mediainfo.registries.THEME_CLASSES", {"glow": _HealthyTheme})
    out = _output(_config(themes={"glow": {"enabled": True}}))
    assert out.health_check() is None


def test_health_check_none_when_no_themes_enabled():
    out = _output()
    assert out.health_check() is None


def test_health_check_aggregates_degraded_theme(monkeypatch):
    monkeypatch.setattr(
        "mediainfo.config.themes.THEMES_CONFIG_TYPES",
        {"glow": _FakeGlowConfig},
    )
    monkeypatch.setattr("mediainfo.registries.THEME_CLASSES", {"glow": _DegradedTheme})
    out = _output(_config(themes={"glow": {"enabled": True}}))

    assert out.health_check() == {
        "themes": {"glow": {"degraded": True, "reason": "something is off"}}
    }


class _RaisingHealthTheme(DisplayTheme):
    name = "glow"

    def health_detail(self, config):
        raise RuntimeError("boom")


def test_health_check_swallows_exception_from_one_theme(monkeypatch):
    monkeypatch.setattr(
        "mediainfo.config.themes.THEMES_CONFIG_TYPES",
        {"glow": _FakeGlowConfig},
    )
    monkeypatch.setattr("mediainfo.registries.THEME_CLASSES", {"glow": _RaisingHealthTheme})
    out = _output(_config(themes={"glow": {"enabled": True}}))

    assert out.health_check() is None  # doesn't raise, just reports nothing for this theme


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
        "mediainfo.config.themes.THEMES_CONFIG_TYPES",
        {"glow": _FakeGlowConfig},
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

    resp = _client(out).get(f"/image/current?v={v}")
    assert resp.status_code == 200
    assert resp.data == b"derived-bytes"


# ---------------------------------------------------------------------------
# Auto-rotate (Phase 8) - cycling between named presets (subsets of the
# enabled themes) instead of always showing every enabled theme's data at
# once. Two fake themes so filtering has something real to filter.
# ---------------------------------------------------------------------------


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class _FakeVinylConfig:
    enabled: bool = False


class _FakeVinylTheme(DisplayTheme):
    name = "vinyl"

    def client_assets(self, config):
        return ThemeClientAssets(css=".vinyl { color: black; }", js="console.log('vinyl');")

    def prepare(self, now_playing, artwork, image_path, cache, media_data, config):
        return ThemeRenderResult(extra_payload={"spinning": True})


@pytest.fixture
def fake_two_themes(monkeypatch):
    monkeypatch.setattr(
        "mediainfo.config.themes.THEMES_CONFIG_TYPES",
        {"glow": _FakeGlowConfig, "vinyl": _FakeVinylConfig},
    )
    monkeypatch.setattr(
        "mediainfo.registries.THEME_CLASSES",
        {"glow": _FakeGlowTheme, "vinyl": _FakeVinylTheme},
    )


def _two_theme_output(**auto_rotate_kwargs):
    config = _config(
        themes={"glow": {"enabled": True}, "vinyl": {"enabled": True}},
        **({"auto_rotate": auto_rotate_kwargs} if auto_rotate_kwargs else {}),
    )
    out = _output(config)
    out.on_new_item(_music(), cache=MagicMock())
    return out


def test_auto_rotate_off_by_default_shows_every_enabled_theme(fake_two_themes, tmp_path):
    out = _two_theme_output()
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")
    out.update(_music(), _artwork(), img)

    payload = out._get_payload()
    assert set(payload["themes"]) == {"glow", "vinyl"}
    assert "active_preset" not in payload


def test_auto_rotate_enabled_no_presets_shows_every_enabled_theme(fake_two_themes, tmp_path):
    out = _two_theme_output(enabled=True)  # presets left empty
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")
    out.update(_music(), _artwork(), img)

    payload = out._get_payload()
    assert set(payload["themes"]) == {"glow", "vinyl"}
    assert "active_preset" not in payload


def test_auto_rotate_filters_payload_to_active_preset(fake_two_themes, tmp_path):
    out = _two_theme_output(
        enabled=True,
        presets={"minimal": ["glow"], "full": ["glow", "vinyl"]},
    )
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")
    out.update(_music(), _artwork(), img)

    payload = out._get_payload()
    assert payload["active_preset"] == "minimal"
    assert set(payload["themes"]) == {"glow"}


def test_auto_rotate_still_loads_css_js_for_themes_outside_active_preset(
    fake_two_themes,
):
    """Filtering only affects the per-tick payload, not the once-baked
    page CSS/JS - a preset switch must not require a page reload."""
    out = _two_theme_output(enabled=True, presets={"minimal": ["glow"]})
    assert ".glow" in out._theme_css
    assert ".vinyl" in out._theme_css  # vinyl's CSS still ships, even though filtered out


def test_advance_preset_rotates_to_next_and_pushes(fake_two_themes, tmp_path):
    out = _two_theme_output(
        enabled=True,
        presets={"minimal": ["glow"], "full": ["glow", "vinyl"]},
    )
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")
    out.update(_music(), _artwork(), img)
    conn = _FakeConn()
    out._clients = {conn}

    out._advance_preset()

    assert out._active_preset == "full"
    payload = json.loads(conn.sent[-1])
    assert payload["active_preset"] == "full"
    assert set(payload["themes"]) == {"glow", "vinyl"}


def test_advance_preset_wraps_around(fake_two_themes, tmp_path):
    out = _two_theme_output(
        enabled=True,
        presets={"minimal": ["glow"], "full": ["glow", "vinyl"]},
    )
    out._advance_preset()
    assert out._active_preset == "full"
    out._advance_preset()
    assert out._active_preset == "minimal"


def test_auto_rotate_preset_naming_unenabled_theme_is_logged(fake_two_themes, caplog):
    _two_theme_output(enabled=True, presets={"oops": ["glow", "nonexistent"]})
    assert "oops" in caplog.text
    assert "nonexistent" in caplog.text


# ---------------------------------------------------------------------------
# Conditioned presets (`when`) - a group that auto-activates and pins for a
# given media type, instead of waiting its turn in the timer rotation.
# ---------------------------------------------------------------------------


def test_conditioned_preset_pins_regardless_of_rotation_pointer(fake_two_themes, tmp_path):
    out = _two_theme_output(
        enabled=True,
        presets={
            "music_group": {"themes": ["glow"], "when": ["music"]},
            "minimal": ["vinyl"],
        },
    )
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")
    out.update(_music(), _artwork(), img)

    payload = out._get_payload()
    assert payload["active_preset"] == "music_group"
    assert set(payload["themes"]) == {"glow"}

    # Advancing the (unconditioned) rotation pool must not disturb the pin -
    # the pointer is free to move in the background, but the conditioned
    # match always wins while music is still playing.
    out._advance_preset()
    payload = out._get_payload()
    assert payload["active_preset"] == "music_group"
    assert set(payload["themes"]) == {"glow"}


def test_no_matching_conditioned_preset_falls_back_to_rotation(fake_two_themes, tmp_path):
    out = _two_theme_output(
        enabled=True,
        presets={
            "music_group": {"themes": ["glow"], "when": ["music"]},
            "minimal": ["vinyl"],
        },
    )
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")
    out.update(_movie(), _artwork(), img)

    # No group claims "movie" - behaves exactly as if music_group didn't
    # exist, falling back to the unconditioned rotation pool.
    payload = out._get_payload()
    assert payload["active_preset"] == "minimal"
    assert set(payload["themes"]) == {"vinyl"}


def test_only_conditioned_presets_no_match_shows_every_enabled_theme(fake_two_themes, tmp_path):
    out = _two_theme_output(
        enabled=True,
        presets={"music_group": {"themes": ["glow"], "when": ["music"]}},
    )
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")
    out.update(_movie(), _artwork(), img)

    payload = out._get_payload()
    assert "active_preset" not in payload
    assert set(payload["themes"]) == {"glow", "vinyl"}


def test_idle_when_maps_to_wallpaper_media_type(fake_two_themes, tmp_path):
    out = _two_theme_output(
        enabled=True,
        presets={"idle_group": {"themes": ["glow"], "when": ["idle"]}},
    )
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")
    out.update(_wallpaper(), _artwork(), img)

    payload = out._get_payload()
    assert payload["active_preset"] == "idle_group"
    assert set(payload["themes"]) == {"glow"}


def test_conflicting_when_first_preset_wins_with_warning(fake_two_themes, caplog, tmp_path):
    out = _two_theme_output(
        enabled=True,
        presets={
            "a": {"themes": ["glow"], "when": ["music"]},
            "b": {"themes": ["vinyl"], "when": ["music"]},
        },
    )
    img = tmp_path / "abc.jpg"
    img.write_bytes(b"x")
    out.update(_music(), _artwork(), img)

    payload = out._get_payload()
    assert payload["active_preset"] == "a"
    assert set(payload["themes"]) == {"glow"}
    assert "a" in caplog.text
    assert "b" in caplog.text


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

    body = _client(out).get("/").data.decode()
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

    resp = _client(out).get(f"/image/current?v={v}")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"

    body = _client(out).get("/").data.decode()
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

    out = _output(
        _config(
            themes={
                "color_palette": {"enabled": True},
                "blurred_background": {"enabled": True},
            }
        )
    )
    out.on_new_item(_music(), cache=cache)
    out.update(_music(), _artwork(), img_path)

    body = _client(out).get("/").data.decode()
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
    from mediainfo.stores.media_data_store import MediaDataStore

    wc_path = tmp_path / "wc.png"
    wc_path.write_bytes(b"fake-wordcloud-png")
    media_data = MagicMock(spec=MediaDataStore)
    media_data.get_track_wordcloud.return_value = wc_path

    out = _output(_config(themes={"word_cloud": {"enabled": True}}))
    out.set_media_data_store(media_data)
    assert out._themes[0].name == "word_cloud"

    song = NowPlaying(
        source="kodi",
        media_type="music",
        title="Bohemian Rhapsody",
        subtitle="Queen",
        album="A Night at the Opera",
    )
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")
    out.on_new_item(song, cache=MagicMock())
    out.update(song, _artwork(), img_path)

    payload = out._get_payload()
    image_url = payload["themes"]["word_cloud"]["image"]
    v = image_url.split("v=")[1]

    resp = _client(out).get(f"/image/current?v={v}")
    assert resp.status_code == 200
    assert resp.data == b"fake-wordcloud-png"


def test_real_word_cloud_theme_end_to_end_movie(tmp_path):
    from PIL import Image

    from mediainfo.cache import ImageCache

    img_path = tmp_path / "poster.jpg"
    Image.new("RGB", (64, 64), (30, 60, 90)).save(img_path)
    cache = ImageCache(tmp_path / "cache")

    out = _output(_config(themes={"word_cloud": {"enabled": True}}))
    movie = NowPlaying(
        source="kodi",
        media_type="movie",
        title="Alien",
        summary="A crew in deep space.",
    )

    out.on_new_item(movie, cache=cache)
    out.update(movie, _artwork(), img_path)

    payload = out._get_payload()
    image_url = payload["themes"]["word_cloud"]["image"]
    v = image_url.split("v=")[1]

    resp = _client(out).get(f"/image/current?v={v}")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"

    body = _client(out).get("/").data.decode()
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

    body = _client(out).get("/").data.decode()
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

    body = _client(out).get("/").data.decode()
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

    body = _client(out).get("/").data.decode()
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


def test_real_media_mosaic_theme_end_to_end(tmp_path):
    from PIL import Image

    from mediainfo.cache import ImageCache

    paths = []
    for i in range(3):
        p = tmp_path / f"art{i}.jpg"
        Image.new("RGB", (64, 64), (i * 60, 50, 90)).save(p)
        paths.append(p)
    cache = ImageCache(tmp_path / "cache")

    album = NowPlaying(
        source="kodi",
        media_type="music",
        title="Song",
        subtitle="Artist",
        images=[Artwork(url=f"file://{p}", label=f"Art {i}") for i, p in enumerate(paths)],
    )

    out = _output(_config(themes={"media_mosaic": {"enabled": True}}))
    assert out._themes[0].name == "media_mosaic"

    out.on_new_item(album, cache=cache)
    out.update(album, Artwork(url=f"file://{paths[0]}", label="Art 0"), paths[0])

    payload = out._get_payload()
    image_url = payload["themes"]["media_mosaic"]["image"]
    v = image_url.split("v=")[1]

    resp = _client(out).get(f"/image/current?v={v}")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"

    body = _client(out).get("/").data.decode()
    assert body.count("window.themeHandlers.media_mosaic = function") == 1


def test_real_timeline_theme_end_to_end_with_discography(tmp_path):
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")

    out = _output(_config(themes={"timeline": {"enabled": True, "max_albums": 5}}))
    assert out._themes[0].name == "timeline"

    song = NowPlaying(
        source="kodi",
        media_type="music",
        title="Kashmir",
        subtitle="Led Zeppelin",
        album="Physical Graffiti",
        discography=["IV – Stairway to Heaven", "Physical Graffiti – Kashmir"],
    )
    out.on_new_item(song, cache=MagicMock())
    out.update(song, _artwork(), img_path)

    payload = out._get_payload()
    assert payload["themes"]["timeline"]["current"] == "Physical Graffiti"
    assert "IV" in payload["themes"]["timeline"]["albums"]
    assert out.health_check() is None  # not degraded - real discography was available

    body = _client(out).get("/").data.decode()
    assert body.count("window.themeHandlers.timeline = function") == 1


def test_real_timeline_theme_end_to_end_degraded_reported_on_health(tmp_path):
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")

    out = _output(_config(themes={"timeline": {"enabled": True}}))
    song = NowPlaying(
        source="kodi",
        media_type="music",
        title="Kashmir",
        subtitle="Led Zeppelin",
        album="Physical Graffiti",
        discography=[],
    )
    out.on_new_item(song, cache=MagicMock())
    out.update(song, _artwork(), img_path)

    payload = out._get_payload()
    assert payload["themes"]["timeline"]["albums"] == ["Physical Graffiti"]

    health = out.health_check()
    assert health["themes"]["timeline"]["degraded"] is True


def test_real_equalizer_theme_end_to_end_music(tmp_path):
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")

    out = _output(_config(themes={"equalizer": {"enabled": True, "style": "wave"}}))
    assert out._themes[0].name == "equalizer"

    out.on_new_item(_music(), cache=MagicMock())
    out.update(_music(), _artwork(), img_path)

    payload = out._get_payload()
    assert payload["themes"]["equalizer"] == {"active": True}

    body = _client(out).get("/").data.decode()
    assert body.count("window.themeHandlers.equalizer = function") == 1
    assert "style-wave" in body


def test_real_equalizer_theme_end_to_end_movie_produces_nothing(tmp_path):
    img_path = tmp_path / "poster.jpg"
    img_path.write_bytes(b"x")

    out = _output(_config(themes={"equalizer": {"enabled": True}}))
    movie = NowPlaying(source="kodi", media_type="movie", title="Alien")

    out.on_new_item(movie, cache=MagicMock())
    out.update(movie, _artwork(), img_path)

    payload = out._get_payload()
    assert "equalizer" not in payload.get("themes", {})


def test_real_lyrics_ticker_theme_end_to_end_music(tmp_path):
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")

    out = _output(_config(themes={"lyrics_ticker": {"enabled": True, "position": "bottom"}}))
    assert out._themes[0].name == "lyrics_ticker"

    song = _music()
    song.synced_lyrics = "[00:12.50]Davy's on the road again\n[00:16.00]hear him singing"
    song.position_seconds = 13.0
    song.duration_seconds = 200.0
    out.on_new_item(song, cache=MagicMock())
    out.update(song, _artwork(), img_path)

    payload = out._get_payload()
    cues = payload["themes"]["lyrics_ticker"]["cues"]
    assert cues == [
        {"t": 12.5, "text": "Davy's on the road again"},
        {"t": 16.0, "text": "hear him singing"},
    ]
    assert out.health_check() is None

    body = _client(out).get("/").data.decode()
    assert body.count("window.themeHandlers.lyrics_ticker = function") == 1
    assert "position-bottom" in body


def test_real_lyrics_ticker_theme_end_to_end_no_synced_lyrics_reported_on_health(
    tmp_path,
):
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")

    out = _output(_config(themes={"lyrics_ticker": {"enabled": True}}))
    song = _music()
    song.synced_lyrics = ""
    out.on_new_item(song, cache=MagicMock())
    out.update(song, _artwork(), img_path)

    payload = out._get_payload()
    assert "lyrics_ticker" not in payload.get("themes", {})

    health = out.health_check()
    assert health["themes"]["lyrics_ticker"]["degraded"] is True


def test_real_progress_bar_theme_end_to_end_music(tmp_path):
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")

    out = _output(
        _config(themes={"progress_bar": {"enabled": True, "position": "top", "color": "#ff8800"}})
    )
    assert out._themes[0].name == "progress_bar"

    song = _music()
    song.position_seconds = 42.5
    song.duration_seconds = 180.0
    out.on_new_item(song, cache=MagicMock())
    out.update(song, _artwork(), img_path)

    payload = out._get_payload()
    assert payload["themes"]["progress_bar"] == {
        "position_seconds": 42.5,
        "duration_seconds": 180.0,
        "color": "#ff8800",
    }

    body = _client(out).get("/").data.decode()
    assert body.count("window.themeHandlers.progress_bar = function") == 1
    assert "position-top" in body


def test_real_progress_bar_theme_end_to_end_movie_with_position(tmp_path):
    img_path = tmp_path / "poster.jpg"
    img_path.write_bytes(b"x")

    out = _output(_config(themes={"progress_bar": {"enabled": True}}))
    movie = NowPlaying(source="kodi", media_type="movie", title="Alien")
    movie.position_seconds = 10.0
    movie.duration_seconds = 6000.0

    out.on_new_item(movie, cache=MagicMock())
    out.update(movie, _artwork(), img_path)

    payload = out._get_payload()
    assert payload["themes"]["progress_bar"]["duration_seconds"] == 6000.0


def test_real_progress_bar_theme_end_to_end_no_position_produces_nothing(tmp_path):
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")

    out = _output(_config(themes={"progress_bar": {"enabled": True}}))
    song = _music()

    out.on_new_item(song, cache=MagicMock())
    out.update(song, _artwork(), img_path)

    payload = out._get_payload()
    assert "progress_bar" not in payload.get("themes", {})


def test_real_cast_mosaic_theme_end_to_end(tmp_path):
    """Exercises the multi-image derived_image_paths -> /image/current
    plumbing end-to-end (regression-style test analogous to
    test_derived_theme_image_is_servable, but for the multi-image path
    added for Cast/Crew Mosaic)."""
    from PIL import Image

    from mediainfo.cache import ImageCache

    photo_paths = []
    for i, name in enumerate(["keanu", "laurence"]):
        p = tmp_path / f"{name}.jpg"
        Image.new("RGB", (50, 50), (i * 60, 50, 90)).save(p)
        photo_paths.append(p)
    poster_path = tmp_path / "poster.jpg"
    Image.new("RGB", (64, 64), (10, 10, 10)).save(poster_path)
    cache = ImageCache(tmp_path / "cache")

    movie = NowPlaying(
        source="kodi",
        media_type="movie",
        title="The Matrix",
        cast=[
            {
                "name": "Keanu Reeves",
                "character": "Neo",
                "photo_url": f"file://{photo_paths[0]}",
            },
            {
                "name": "Laurence Fishburne",
                "character": "Morpheus",
                "photo_url": f"file://{photo_paths[1]}",
            },
        ],
    )

    out = _output(_config(themes={"cast_mosaic": {"enabled": True}}))
    assert out._themes[0].name == "cast_mosaic"

    out.on_new_item(movie, cache=cache)
    out.update(movie, Artwork(url=f"file://{poster_path}", label="Poster"), poster_path)

    payload = out._get_payload()
    cast_payload = payload["themes"]["cast_mosaic"]["cast"]
    assert len(cast_payload) == 2
    assert cast_payload[0]["name"] == "Keanu Reeves"
    assert cast_payload[0]["character"] == "Neo"
    assert out.health_check() is None

    for member in cast_payload:
        v = member["image"].split("v=")[1]
        resp = _client(out).get(f"/image/current?v={v}")
        assert resp.status_code == 200

    body = _client(out).get("/").data.decode()
    assert body.count("window.themeHandlers.cast_mosaic = function") == 1


def test_real_cast_mosaic_theme_end_to_end_no_cast_reported_on_health(tmp_path):
    img_path = tmp_path / "poster.jpg"
    img_path.write_bytes(b"x")

    out = _output(_config(themes={"cast_mosaic": {"enabled": True}}))
    movie = NowPlaying(source="kodi", media_type="movie", title="The Matrix", cast=[])

    out.on_new_item(movie, cache=MagicMock())
    out.update(movie, _artwork(), img_path)

    payload = out._get_payload()
    assert "cast_mosaic" not in payload.get("themes", {})

    health = out.health_check()
    assert health["themes"]["cast_mosaic"]["degraded"] is True


def test_theme_image_urls_get_the_computed_prefix_flat_case(tmp_path):
    # ken_burns/vinyl embed a single flat "image" key in extra_payload -
    # see _prefix_image_urls() in mediainfo/outputs/themes.py.
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")

    out = _output(_config(themes={"vinyl": {"enabled": True}}))
    out.build_http_blueprint("/themes")  # wiring.py calls this before any update()
    out.on_new_item(_music(), cache=MagicMock())
    out.update(_music(), _artwork(), img_path)

    payload = out._get_payload()
    assert payload["themes"]["vinyl"]["image"] == f"/themes/image/current?v={img_path.stem}"


def test_theme_image_urls_get_the_computed_prefix_nested_case(tmp_path):
    # Cast Mosaic embeds a list of dicts, each with its own "image" key,
    # nested under extra_payload["cast"] - proves _prefix_image_urls()
    # walks arbitrary nesting, not just a top-level "image" key.
    from PIL import Image

    from mediainfo.cache import ImageCache

    photo_path = tmp_path / "keanu.jpg"
    Image.new("RGB", (50, 50), (10, 20, 30)).save(photo_path)
    poster_path = tmp_path / "poster.jpg"
    Image.new("RGB", (64, 64), (10, 10, 10)).save(poster_path)
    cache = ImageCache(tmp_path / "cache")

    movie = NowPlaying(
        source="kodi",
        media_type="movie",
        title="The Matrix",
        cast=[{"name": "Keanu Reeves", "character": "Neo", "photo_url": f"file://{photo_path}"}],
    )

    out = _output(_config(themes={"cast_mosaic": {"enabled": True}}))
    out.build_http_blueprint("/themes")
    out.on_new_item(movie, cache=cache)
    out.update(movie, Artwork(url=f"file://{poster_path}", label="Poster"), poster_path)

    payload = out._get_payload()
    image_url = payload["themes"]["cast_mosaic"]["cast"][0]["image"]
    assert image_url.startswith("/themes/image/current?v=")

    resp = _client(out, url_prefix="/themes").get(image_url)
    assert resp.status_code == 200


def test_real_artist_spotlight_theme_end_to_end_music(tmp_path):
    from mediainfo.stores.media_data_store import MediaDataStore

    photo_path = tmp_path / "artist.jpg"
    photo_path.write_bytes(b"fake-photo")
    media_data = MagicMock(spec=MediaDataStore)
    media_data.get_artist_photo.return_value = photo_path

    out = _output(_config(themes={"artist_spotlight": {"enabled": True}}))
    out.set_media_data_store(media_data)
    assert out._themes[0].name == "artist_spotlight"

    song = _music(title="Bohemian Rhapsody", artist="Queen")
    song.summary = "A British rock band."
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")
    out.on_new_item(song, cache=MagicMock())
    out.update(song, _artwork(), img_path)

    payload = out._get_payload()
    assert payload["themes"]["artist_spotlight"]["name"] == "Queen"
    assert payload["themes"]["artist_spotlight"]["bio"] == "A British rock band."
    media_data.get_artist_photo.assert_called_with("Queen")
    assert out.health_check() is None

    image_url = payload["themes"]["artist_spotlight"]["image"]
    v = image_url.split("v=")[1]
    resp = _client(out).get(f"/image/current?v={v}")
    assert resp.status_code == 200
    assert resp.data == b"fake-photo"

    body = _client(out).get("/").data.decode()
    assert body.count("window.themeHandlers.artist_spotlight = function") == 1


def test_real_artist_spotlight_theme_end_to_end_no_photo_reported_on_health(tmp_path):
    from mediainfo.stores.media_data_store import MediaDataStore

    media_data = MagicMock(spec=MediaDataStore)
    media_data.get_artist_photo.return_value = None

    out = _output(_config(themes={"artist_spotlight": {"enabled": True}}))
    out.set_media_data_store(media_data)

    song = _music()
    img_path = tmp_path / "art.jpg"
    img_path.write_bytes(b"x")
    out.on_new_item(song, cache=MagicMock())
    out.update(song, _artwork(), img_path)

    payload = out._get_payload()
    assert "artist_spotlight" not in payload.get("themes", {})

    health = out.health_check()
    assert health["themes"]["artist_spotlight"]["degraded"] is True


# ---------------------------------------------------------------------------
# attach() - see mediainfo.app_services.AppServices
# ---------------------------------------------------------------------------


def test_attach_wires_media_data_store():
    from mediainfo.app_services import AppServices
    from mediainfo.stores.media_data_store import MediaDataStore

    out = _output()
    media_data = MagicMock(spec=MediaDataStore)

    out.attach(AppServices(mediadata_store=media_data))

    assert out.media_data is media_data


def test_attach_passes_through_none_media_data_store():
    from mediainfo.app_services import AppServices

    out = _output()
    out.attach(AppServices(mediadata_store=None))
    assert out.media_data is None
