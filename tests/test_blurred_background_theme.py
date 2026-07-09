"""Tests for the Blurred Background theme
(mediainfo/themes/blurred_background.py)."""

from PIL import Image

from mediainfo.cache import ImageCache
from mediainfo.config.themes import BlurredBackgroundConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.blurred_background import BlurredBackgroundTheme, _DOWNSCALE_SIZE


def _sharp_checkerboard(width=800, height=800):
    img = Image.new("RGB", (width, height), (0, 0, 0))
    for x in range(0, width, 20):
        for y in range(0, height, 20):
            if (x // 20 + y // 20) % 2 == 0:
                for dx in range(20):
                    for dy in range(20):
                        if x + dx < width and y + dy < height:
                            img.putpixel((x + dx, y + dy), (255, 255, 255))
    return img


def _now_playing():
    return NowPlaying(source="kodi", media_type="music", title="Song", subtitle="Artist")


def _artwork():
    return Artwork(url="https://example.com/art.jpg", label="Album art")


# ---------------------------------------------------------------------------
# _build()
# ---------------------------------------------------------------------------

def test_build_downscales():
    img = _sharp_checkerboard(1600, 1600)
    result = BlurredBackgroundTheme._build(img, BlurredBackgroundConfig())
    assert max(result.size) <= _DOWNSCALE_SIZE


def test_build_blurs_away_sharp_edges():
    img = _sharp_checkerboard()
    result = BlurredBackgroundTheme._build(img, BlurredBackgroundConfig(blur_radius=40, brightness=1.0))
    # A heavily blurred checkerboard should have no pixel at the pure
    # extremes anymore - everything gets smeared toward gray.
    extremes = sum(
        1 for pixel in result.getdata() if pixel in ((0, 0, 0), (255, 255, 255))
    )
    assert extremes == 0


def test_build_darkens_when_brightness_below_one():
    img = _sharp_checkerboard()
    unchanged = BlurredBackgroundTheme._build(img, BlurredBackgroundConfig(brightness=1.0))
    darkened = BlurredBackgroundTheme._build(img, BlurredBackgroundConfig(brightness=0.3))

    def avg_brightness(image):
        pixels = list(image.convert("L").getdata())
        return sum(pixels) / len(pixels)

    assert avg_brightness(darkened) < avg_brightness(unchanged)


# ---------------------------------------------------------------------------
# prepare()
# ---------------------------------------------------------------------------

def test_prepare_returns_derived_image(tmp_path):
    img_path = tmp_path / "art.jpg"
    _sharp_checkerboard().save(img_path)
    cache = ImageCache(tmp_path / "cache")
    theme = BlurredBackgroundTheme()

    result = theme.prepare(
        _now_playing(), _artwork(), img_path, cache, None, BlurredBackgroundConfig(),
    )

    assert result is not None
    assert result.derived_image_path.exists()
    assert result.derived_image_path.suffix == ".png"
    assert result.derived_image_path != img_path


def test_prepare_reuses_cache_on_repeat_call(tmp_path):
    img_path = tmp_path / "art.jpg"
    _sharp_checkerboard().save(img_path)
    cache = ImageCache(tmp_path / "cache")
    theme = BlurredBackgroundTheme()
    config = BlurredBackgroundConfig()

    result1 = theme.prepare(_now_playing(), _artwork(), img_path, cache, None, config)
    mtime1 = result1.derived_image_path.stat().st_mtime_ns

    result2 = theme.prepare(_now_playing(), _artwork(), img_path, cache, None, config)
    mtime2 = result2.derived_image_path.stat().st_mtime_ns

    assert result1.derived_image_path == result2.derived_image_path
    assert mtime1 == mtime2  # not rewritten - a real cache hit, not a rebuild


def test_prepare_different_settings_produce_different_files(tmp_path):
    img_path = tmp_path / "art.jpg"
    _sharp_checkerboard().save(img_path)
    cache = ImageCache(tmp_path / "cache")
    theme = BlurredBackgroundTheme()

    result1 = theme.prepare(
        _now_playing(), _artwork(), img_path, cache, None, BlurredBackgroundConfig(blur_radius=20),
    )
    result2 = theme.prepare(
        _now_playing(), _artwork(), img_path, cache, None, BlurredBackgroundConfig(blur_radius=60),
    )

    assert result1.derived_image_path != result2.derived_image_path


def test_prepare_returns_none_for_unreadable_image(tmp_path):
    cache = ImageCache(tmp_path / "cache")
    theme = BlurredBackgroundTheme()
    result = theme.prepare(
        _now_playing(), _artwork(), tmp_path / "missing.jpg", cache, None, BlurredBackgroundConfig(),
    )
    assert result is None


# ---------------------------------------------------------------------------
# client_assets()
# ---------------------------------------------------------------------------

def test_client_assets_registers_theme_handler():
    theme = BlurredBackgroundTheme()
    assets = theme.client_assets(BlurredBackgroundConfig())
    assert "window.themeHandlers.blurred_background" in assets.js
    assert "theme-blurred-background" in assets.css
