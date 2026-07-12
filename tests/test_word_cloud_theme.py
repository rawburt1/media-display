"""Tests for the Word Cloud theme (mediainfo/themes/word_cloud.py)."""

from unittest.mock import Mock

from PIL import Image

from mediainfo.cache import ImageCache
from mediainfo.config.themes import WordCloudConfig
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.word_cloud import WordCloudTheme


def _music(**kwargs):
    defaults = dict(
        source="kodi",
        media_type="music",
        title="Davy's on the Road Again",
        subtitle="Manfred Mann's Earth Band",
        album="Watch",
        year=1978,
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def _movie(**kwargs):
    defaults = dict(
        source="kodi", media_type="movie", title="Alien", summary="A crew in deep space."
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def _artwork():
    return Artwork(url="https://example.com/art.jpg", label="Album art")


# ---------------------------------------------------------------------------
# prepare() - music branch
# ---------------------------------------------------------------------------


def test_music_calls_get_track_wordcloud(tmp_path):
    wc_path = tmp_path / "wc.png"
    wc_path.write_bytes(b"fake-png")
    media_data = Mock(spec=MediaDataStore)
    media_data.get_track_wordcloud.return_value = wc_path

    theme = WordCloudTheme()
    result = theme.prepare(
        _music(),
        _artwork(),
        tmp_path / "art.jpg",
        Mock(),
        media_data,
        WordCloudConfig(),
    )

    media_data.get_track_wordcloud.assert_called_once_with(
        "Manfred Mann's Earth Band",
        "Watch",
        "Davy's on the Road Again",
        1978,
    )
    assert result.derived_image_path == wc_path


def test_music_returns_none_without_media_data_store(tmp_path):
    theme = WordCloudTheme()
    result = theme.prepare(
        _music(), _artwork(), tmp_path / "art.jpg", Mock(), None, WordCloudConfig()
    )
    assert result is None


def test_music_returns_none_when_store_finds_no_wordcloud(tmp_path):
    media_data = Mock(spec=MediaDataStore)
    media_data.get_track_wordcloud.return_value = None
    theme = WordCloudTheme()
    result = theme.prepare(
        _music(),
        _artwork(),
        tmp_path / "art.jpg",
        Mock(),
        media_data,
        WordCloudConfig(),
    )
    assert result is None


def test_music_returns_none_without_artist_or_album():
    media_data = Mock(spec=MediaDataStore)
    theme = WordCloudTheme()
    result = theme.prepare(
        _music(subtitle="", album=""),
        _artwork(),
        None,
        Mock(),
        media_data,
        WordCloudConfig(),
    )
    assert result is None
    media_data.get_track_wordcloud.assert_not_called()


def test_music_swallows_store_exception():
    media_data = Mock(spec=MediaDataStore)
    media_data.get_track_wordcloud.side_effect = RuntimeError("boom")
    theme = WordCloudTheme()
    result = theme.prepare(_music(), _artwork(), None, Mock(), media_data, WordCloudConfig())
    assert result is None


# ---------------------------------------------------------------------------
# prepare() - movie/episode branch
# ---------------------------------------------------------------------------


def test_movie_builds_wordcloud_from_summary(tmp_path):
    img_path = tmp_path / "poster.jpg"
    Image.new("RGB", (64, 64), (30, 60, 90)).save(img_path)
    cache = ImageCache(tmp_path / "cache")
    theme = WordCloudTheme()

    result = theme.prepare(_movie(), _artwork(), img_path, cache, None, WordCloudConfig())

    assert result is not None
    assert result.derived_image_path.exists()
    assert result.derived_image_path.suffix == ".png"


def test_episode_also_uses_summary_branch(tmp_path):
    img_path = tmp_path / "poster.jpg"
    Image.new("RGB", (64, 64), (30, 60, 90)).save(img_path)
    cache = ImageCache(tmp_path / "cache")
    theme = WordCloudTheme()

    now_playing = NowPlaying(
        source="kodi",
        media_type="episode",
        title="Breaking Bad",
        summary="A teacher turns to crime.",
    )
    result = theme.prepare(now_playing, _artwork(), img_path, cache, None, WordCloudConfig())

    assert result is not None


def test_movie_returns_none_without_summary(tmp_path):
    img_path = tmp_path / "poster.jpg"
    Image.new("RGB", (64, 64), (30, 60, 90)).save(img_path)
    cache = ImageCache(tmp_path / "cache")
    theme = WordCloudTheme()

    result = theme.prepare(_movie(summary=""), _artwork(), img_path, cache, None, WordCloudConfig())

    assert result is None


def test_movie_reuses_cache_on_repeat_call(tmp_path):
    img_path = tmp_path / "poster.jpg"
    Image.new("RGB", (64, 64), (30, 60, 90)).save(img_path)
    cache = ImageCache(tmp_path / "cache")
    theme = WordCloudTheme()

    result1 = theme.prepare(_movie(), _artwork(), img_path, cache, None, WordCloudConfig())
    mtime1 = result1.derived_image_path.stat().st_mtime_ns
    result2 = theme.prepare(_movie(), _artwork(), img_path, cache, None, WordCloudConfig())
    mtime2 = result2.derived_image_path.stat().st_mtime_ns

    assert result1.derived_image_path == result2.derived_image_path
    assert mtime1 == mtime2


def test_movie_different_summary_produces_different_file(tmp_path):
    img_path = tmp_path / "poster.jpg"
    Image.new("RGB", (64, 64), (30, 60, 90)).save(img_path)
    cache = ImageCache(tmp_path / "cache")
    theme = WordCloudTheme()

    result1 = theme.prepare(
        _movie(summary="A crew in deep space."),
        _artwork(),
        img_path,
        cache,
        None,
        WordCloudConfig(),
    )
    result2 = theme.prepare(
        _movie(summary="A wizard goes on a quest."),
        _artwork(),
        img_path,
        cache,
        None,
        WordCloudConfig(),
    )

    assert result1.derived_image_path != result2.derived_image_path


def test_movie_returns_none_for_unreadable_artwork(tmp_path):
    cache = ImageCache(tmp_path / "cache")
    theme = WordCloudTheme()
    result = theme.prepare(
        _movie(), _artwork(), tmp_path / "missing.jpg", cache, None, WordCloudConfig()
    )
    assert result is None


def test_unsupported_media_type_returns_none(tmp_path):
    theme = WordCloudTheme()
    now_playing = NowPlaying(source="idle", media_type="wallpaper", title="")
    result = theme.prepare(
        now_playing, _artwork(), tmp_path / "art.jpg", Mock(), None, WordCloudConfig()
    )
    assert result is None


# ---------------------------------------------------------------------------
# client_assets()
# ---------------------------------------------------------------------------


def test_client_assets_registers_theme_handler():
    theme = WordCloudTheme()
    assets = theme.client_assets(WordCloudConfig())
    assert "window.themeHandlers.word_cloud" in assets.js
    assert "corner-bottom-right" in assets.js


def test_client_assets_falls_back_to_bottom_right_for_invalid_corner():
    theme = WordCloudTheme()
    assets = theme.client_assets(WordCloudConfig(corner="nonsense; </script>"))
    assert "corner-bottom-right" in assets.js
    assert "nonsense" not in assets.js
