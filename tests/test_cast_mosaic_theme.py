"""Tests for the Cast/Crew Mosaic theme (mediainfo/themes/cast_mosaic.py)."""

from PIL import Image

from mediainfo.cache import ImageCache
from mediainfo.config.themes import CastMosaicConfig
from mediainfo.models import NowPlaying
from mediainfo.themes.cast_mosaic import CastMosaicTheme


def _make_image(path, color=(200, 50, 50)):
    Image.new("RGB", (50, 50), color).save(path)
    return path


def _cast_entry(tmp_path, name, photo_filename=None, character="A role"):
    photo_url = ""
    if photo_filename:
        photo_path = _make_image(tmp_path / photo_filename)
        photo_url = f"file://{photo_path}"
    return {"name": name, "character": character, "photo_url": photo_url}


def _movie(cast=None):
    return NowPlaying(source="kodi", media_type="movie", title="The Matrix", cast=cast or [])


def _episode(cast=None):
    return NowPlaying(source="kodi", media_type="episode", title="Breaking Bad", cast=cast or [])


def _music():
    return NowPlaying(source="kodi", media_type="music", title="Song", subtitle="Artist")


# ---------------------------------------------------------------------------
# prepare()
# ---------------------------------------------------------------------------

def test_resolves_headshots_and_builds_payload(tmp_path):
    art_path = _make_image(tmp_path / "poster.jpg")
    cache = ImageCache(tmp_path / "cache")
    cast = [
        _cast_entry(tmp_path, "Keanu Reeves", "keanu.jpg", "Neo"),
        _cast_entry(tmp_path, "Laurence Fishburne", "laurence.jpg", "Morpheus"),
    ]
    theme = CastMosaicTheme()

    result = theme.prepare(_movie(cast=cast), None, art_path, cache, None, CastMosaicConfig())

    assert result is not None
    assert len(result.derived_image_paths) == 2
    payload_cast = result.extra_payload["cast"]
    assert payload_cast[0]["name"] == "Keanu Reeves"
    assert payload_cast[0]["character"] == "Neo"
    assert payload_cast[0]["image"] == f"/image/current?v={result.derived_image_paths[0].stem}"
    assert theme.health_detail(CastMosaicConfig()) is None


def test_episode_uses_show_level_cast(tmp_path):
    art_path = _make_image(tmp_path / "poster.jpg")
    cache = ImageCache(tmp_path / "cache")
    cast = [_cast_entry(tmp_path, "Bryan Cranston", "bryan.jpg", "Walter White")]

    result = CastMosaicTheme().prepare(_episode(cast=cast), None, art_path, cache, None, CastMosaicConfig())

    assert result is not None
    assert result.extra_payload["cast"][0]["name"] == "Bryan Cranston"


def test_music_returns_none_no_degraded_report(tmp_path):
    art_path = _make_image(tmp_path / "art.jpg")
    cache = ImageCache(tmp_path / "cache")
    theme = CastMosaicTheme()

    result = theme.prepare(_music(), None, art_path, cache, None, CastMosaicConfig())

    assert result is None
    assert theme.health_detail(CastMosaicConfig()) is None


def test_no_cast_data_degrades(tmp_path):
    art_path = _make_image(tmp_path / "poster.jpg")
    cache = ImageCache(tmp_path / "cache")
    theme = CastMosaicTheme()

    result = theme.prepare(_movie(cast=[]), None, art_path, cache, None, CastMosaicConfig())

    assert result is None
    detail = theme.health_detail(CastMosaicConfig())
    assert detail["degraded"] is True
    assert "fetch_cast" in detail["reason"]


def test_cast_entries_with_no_photo_url_are_skipped(tmp_path):
    art_path = _make_image(tmp_path / "poster.jpg")
    cache = ImageCache(tmp_path / "cache")
    cast = [
        _cast_entry(tmp_path, "No Photo Person"),  # no photo_filename -> photo_url == ""
        _cast_entry(tmp_path, "Has Photo", "photo.jpg"),
    ]

    result = CastMosaicTheme().prepare(_movie(cast=cast), None, art_path, cache, None, CastMosaicConfig())

    assert len(result.extra_payload["cast"]) == 1
    assert result.extra_payload["cast"][0]["name"] == "Has Photo"


def test_all_cast_entries_missing_photos_degrades(tmp_path):
    art_path = _make_image(tmp_path / "poster.jpg")
    cache = ImageCache(tmp_path / "cache")
    cast = [_cast_entry(tmp_path, "No Photo Person")]
    theme = CastMosaicTheme()

    result = theme.prepare(_movie(cast=cast), None, art_path, cache, None, CastMosaicConfig())

    assert result is None
    detail = theme.health_detail(CastMosaicConfig())
    assert detail["degraded"] is True
    assert "resolved" in detail["reason"]


def test_respects_max_cast(tmp_path):
    art_path = _make_image(tmp_path / "poster.jpg")
    cache = ImageCache(tmp_path / "cache")
    cast = [_cast_entry(tmp_path, f"Person {i}", f"p{i}.jpg") for i in range(5)]

    result = CastMosaicTheme().prepare(
        _movie(cast=cast), None, art_path, cache, None, CastMosaicConfig(max_cast=2),
    )

    assert len(result.extra_payload["cast"]) == 2


def test_movie_after_degraded_music_clears_state(tmp_path):
    art_path = _make_image(tmp_path / "poster.jpg")
    cache = ImageCache(tmp_path / "cache")
    theme = CastMosaicTheme()

    theme.prepare(_movie(cast=[]), None, art_path, cache, None, CastMosaicConfig())
    assert theme.health_detail(CastMosaicConfig()) is not None

    theme.prepare(_music(), None, art_path, cache, None, CastMosaicConfig())
    assert theme.health_detail(CastMosaicConfig()) is None


# ---------------------------------------------------------------------------
# client_assets()
# ---------------------------------------------------------------------------

def test_client_assets_registers_theme_handler():
    theme = CastMosaicTheme()
    assets = theme.client_assets(CastMosaicConfig())
    assert "window.themeHandlers.cast_mosaic" in assets.js
    assert "theme-cast-mosaic" in assets.css


def test_client_assets_falls_back_to_top_right_for_invalid_corner():
    theme = CastMosaicTheme()
    assets = theme.client_assets(CastMosaicConfig(corner="nonsense; </script>"))
    assert "corner-top-right" in assets.js
    assert "nonsense" not in assets.js
