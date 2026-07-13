"""Tests for the Media Mosaic theme (mediainfo/themes/media_mosaic.py)."""

from unittest.mock import patch

from PIL import Image

from mediainfo.cache import ImageCache
from mediainfo.config.themes import MediaMosaicConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.media_mosaic import MediaMosaicTheme, _grid_dims


def _make_image(path, color):
    Image.new("RGB", (100, 100), color).save(path)
    return path


def _file_artwork(path, **kwargs):
    return Artwork(url=f"file://{path}", **kwargs)


def _now_playing(images):
    return NowPlaying(
        source="kodi", media_type="music", title="Song", subtitle="Artist", images=images
    )


# ---------------------------------------------------------------------------
# _grid_dims
# ---------------------------------------------------------------------------


def test_grid_dims_known_counts_have_no_empty_cells():
    for count in range(1, 7):
        cols, rows = _grid_dims(count)
        assert cols * rows >= count
        # No more than one empty cell for the counts we explicitly packed.
        assert cols * rows - count <= 1


def test_grid_dims_falls_back_for_large_counts():
    cols, rows = _grid_dims(10)
    assert cols * rows >= 10


# ---------------------------------------------------------------------------
# prepare()
# ---------------------------------------------------------------------------


def test_single_image_degrades_to_one_tile(tmp_path):
    art_path = _make_image(tmp_path / "album.jpg", (200, 50, 50))
    cache = ImageCache(tmp_path / "cache")
    now_playing = _now_playing([_file_artwork(art_path, label="Album art")])
    theme = MediaMosaicTheme()

    result = theme.prepare(now_playing, None, art_path, cache, None, MediaMosaicConfig())

    assert result is not None
    assert result.derived_image_path.exists()
    with Image.open(result.derived_image_path) as img:
        assert img.size == (300, 300)  # one tile, no grid


def test_multiple_images_builds_grid(tmp_path):
    paths = [_make_image(tmp_path / f"art{i}.jpg", (i * 40, 50, 50)) for i in range(4)]
    cache = ImageCache(tmp_path / "cache")
    now_playing = _now_playing([_file_artwork(p, label=f"Art {i}") for i, p in enumerate(paths)])
    theme = MediaMosaicTheme()

    result = theme.prepare(now_playing, None, paths[0], cache, None, MediaMosaicConfig())

    assert result is not None
    with Image.open(result.derived_image_path) as img:
        assert img.size == (600, 600)  # 2x2 grid of 300px tiles


def test_excludes_artist_photo_and_wordcloud(tmp_path):
    album = _make_image(tmp_path / "album.jpg", (200, 50, 50))
    artist_photo = _make_image(tmp_path / "artist.jpg", (50, 200, 50))
    wordcloud = _make_image(tmp_path / "wc.png", (50, 50, 200))
    cache = ImageCache(tmp_path / "cache")
    now_playing = _now_playing(
        [
            _file_artwork(album, label="Album art"),
            _file_artwork(artist_photo, label="Artist photo", is_artist_photo=True),
            _file_artwork(wordcloud, label="Word cloud", is_wordcloud=True),
        ]
    )
    theme = MediaMosaicTheme()

    result = theme.prepare(now_playing, None, album, cache, None, MediaMosaicConfig())

    with Image.open(result.derived_image_path) as img:
        assert img.size == (300, 300)  # only the one non-excluded candidate


def test_respects_max_tiles(tmp_path):
    paths = [_make_image(tmp_path / f"art{i}.jpg", (i * 20, 50, 50)) for i in range(6)]
    cache = ImageCache(tmp_path / "cache")
    now_playing = _now_playing([_file_artwork(p, label=f"Art {i}") for i, p in enumerate(paths)])
    theme = MediaMosaicTheme()

    result = theme.prepare(now_playing, None, paths[0], cache, None, MediaMosaicConfig(max_tiles=2))

    with Image.open(result.derived_image_path) as img:
        assert img.size == (600, 300)  # 2 tiles, capped from 6


def test_returns_none_without_any_candidates(tmp_path):
    cache = ImageCache(tmp_path / "cache")
    now_playing = _now_playing([])
    theme = MediaMosaicTheme()
    result = theme.prepare(
        now_playing, None, tmp_path / "art.jpg", cache, None, MediaMosaicConfig()
    )
    assert result is None


def test_returns_none_when_only_excluded_images_present(tmp_path):
    artist_photo = _make_image(tmp_path / "artist.jpg", (50, 200, 50))
    cache = ImageCache(tmp_path / "cache")
    now_playing = _now_playing([_file_artwork(artist_photo, is_artist_photo=True)])
    theme = MediaMosaicTheme()
    result = theme.prepare(now_playing, None, artist_photo, cache, None, MediaMosaicConfig())
    assert result is None


def test_skips_unresolvable_image_but_keeps_others(tmp_path):
    good = _make_image(tmp_path / "good.jpg", (200, 50, 50))
    cache = ImageCache(tmp_path / "cache")
    now_playing = _now_playing(
        [
            _file_artwork(tmp_path / "missing.jpg", label="Missing"),
            _file_artwork(good, label="Good"),
        ]
    )
    theme = MediaMosaicTheme()

    result = theme.prepare(now_playing, None, good, cache, None, MediaMosaicConfig())

    assert result is not None
    with Image.open(result.derived_image_path) as img:
        assert img.size == (300, 300)  # only the resolvable one


def test_reuses_cache_on_repeat_call(tmp_path):
    paths = [_make_image(tmp_path / f"art{i}.jpg", (i * 40, 50, 50)) for i in range(3)]
    cache = ImageCache(tmp_path / "cache")
    now_playing = _now_playing([_file_artwork(p, label=f"Art {i}") for i, p in enumerate(paths)])
    theme = MediaMosaicTheme()
    config = MediaMosaicConfig()

    result1 = theme.prepare(now_playing, None, paths[0], cache, None, config)

    # A repeat call must reuse the cached file rather than rebuilding it -
    # proven directly by spying on the expensive build step, not by mtime
    # equality: ImageCache now bumps mtime on every cache hit too (M2 in
    # docs/architecture-usability-review-2026-07.md - needed for its
    # size-capped LRU eviction to evict by real last-use, not last-build).
    with patch.object(MediaMosaicTheme, "_build_mosaic") as mock_build:
        result2 = theme.prepare(now_playing, None, paths[0], cache, None, config)

    mock_build.assert_not_called()
    assert result1.derived_image_path == result2.derived_image_path


def test_highlights_the_current_tile(tmp_path):
    current = _make_image(tmp_path / "current.jpg", (10, 10, 10))
    other = _make_image(tmp_path / "other.jpg", (10, 10, 10))
    cache = ImageCache(tmp_path / "cache")
    now_playing = _now_playing(
        [_file_artwork(current, label="Current"), _file_artwork(other, label="Other")]
    )
    theme = MediaMosaicTheme()

    result = theme.prepare(now_playing, None, current, cache, None, MediaMosaicConfig())

    with Image.open(result.derived_image_path) as img:
        # The highlighted tile's border pixel should be white; the
        # unhighlighted tile's corresponding pixel should still be the
        # original dark fill color.
        highlighted_corner = img.getpixel((0, 0))
        other_corner = img.getpixel((img.size[0] - 1, 0))
        assert highlighted_corner == (255, 255, 255)
        assert other_corner == (10, 10, 10)


# ---------------------------------------------------------------------------
# client_assets()
# ---------------------------------------------------------------------------


def test_client_assets_registers_theme_handler():
    theme = MediaMosaicTheme()
    assets = theme.client_assets(MediaMosaicConfig())
    assert "window.themeHandlers.media_mosaic" in assets.js
    assert "theme-media-mosaic" in assets.css


def test_client_assets_falls_back_to_top_right_for_invalid_corner():
    theme = MediaMosaicTheme()
    assets = theme.client_assets(MediaMosaicConfig(corner="nonsense; </script>"))
    assert "corner-top-right" in assets.js
    assert "nonsense" not in assets.js
