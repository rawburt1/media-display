"""Tests for the MediaDataStore-backed artwork enricher (album art for
music, poster+fanart for movies/episodes)."""

from typing import Any
from unittest.mock import Mock

from mediainfo.config import MediaDataArtworkEnricherConfig, MediaDataWordcloudConfig
from mediainfo.enrichers.mediadata import MediaDataArtworkEnricher
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying


def _config(wordcloud_enabled: bool = False) -> MediaDataArtworkEnricherConfig:
    return MediaDataArtworkEnricherConfig(
        wordcloud=MediaDataWordcloudConfig(enabled=wordcloud_enabled)
    )


def _song(**kwargs):
    defaults: dict[str, Any] = dict(
        source="youtube", media_type="music",
        title="Comfortably Numb", subtitle="Pink Floyd", album="The Wall",
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def _movie(**kwargs):
    defaults: dict[str, Any] = dict(source="kodi", media_type="movie", title="Alien", year=1979)
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def _episode(**kwargs):
    defaults: dict[str, Any] = dict(source="kodi", media_type="episode", title="Breaking Bad")
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def test_adds_album_art_on_hit(tmp_path):
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.return_value = None
    art_path = tmp_path / "albumart.jpg"
    art_path.write_bytes(b"fake")
    store.get_album_art.return_value = art_path

    np = _song()
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    store.get_album_art.assert_called_once_with("Pink Floyd", "The Wall", None)
    assert len(np.images) == 1
    assert np.images[0].url == f"file://{art_path}"
    assert "mediadata" in np.images[0].label.lower()


def test_does_not_replace_existing_images(tmp_path):
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.return_value = None
    art_path = tmp_path / "albumart.jpg"
    art_path.write_bytes(b"fake")
    store.get_album_art.return_value = art_path

    np = _song(images=[Artwork(url="https://example.com/existing.jpg", label="existing")])
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    assert len(np.images) == 2
    urls = {img.url for img in np.images}
    assert urls == {"https://example.com/existing.jpg", f"file://{art_path}"}


def test_does_not_add_duplicate_url(tmp_path):
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.return_value = None
    art_path = tmp_path / "albumart.jpg"
    art_path.write_bytes(b"fake")
    store.get_album_art.return_value = art_path

    np = _song(images=[Artwork(url=f"file://{art_path}", label="existing")])
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    assert len(np.images) == 1


def test_no_op_on_store_miss():
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.return_value = None
    store.get_album_art.return_value = None

    np = _song()
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    assert np.images == []


def test_no_op_when_store_is_none():
    np = _song()
    MediaDataArtworkEnricher(config=_config(), store=None).enrich(np)
    assert np.images == []


def test_adds_movie_poster_and_fanart_on_hit(tmp_path):
    store = Mock(spec=MediaDataStore)
    poster_path = tmp_path / "poster.jpg"
    poster_path.write_bytes(b"fake")
    fanart_path = tmp_path / "fanart.jpg"
    fanart_path.write_bytes(b"fake")
    store.get_movie_poster.return_value = poster_path
    store.get_movie_fanart.return_value = fanart_path

    np = _movie()
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    store.get_movie_poster.assert_called_once_with("Alien", 1979)
    store.get_movie_fanart.assert_called_once_with("Alien", 1979)
    urls = {img.url for img in np.images}
    assert urls == {f"file://{poster_path}", f"file://{fanart_path}"}
    store.get_album_art.assert_not_called()


def test_adds_series_poster_and_fanart_on_hit(tmp_path):
    store = Mock(spec=MediaDataStore)
    poster_path = tmp_path / "poster.jpg"
    poster_path.write_bytes(b"fake")
    store.get_series_poster.return_value = poster_path
    store.get_series_fanart.return_value = None

    np = _episode()
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    store.get_series_poster.assert_called_once_with("Breaking Bad", None)
    store.get_series_fanart.assert_called_once_with("Breaking Bad", None)
    assert len(np.images) == 1
    assert np.images[0].url == f"file://{poster_path}"


def test_movie_no_op_on_store_miss():
    store = Mock(spec=MediaDataStore)
    store.get_movie_poster.return_value = None
    store.get_movie_fanart.return_value = None

    np = _movie()
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    assert np.images == []


def test_movie_no_op_without_title():
    store = Mock(spec=MediaDataStore)
    np = _movie(title="")
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)
    assert np.images == []
    store.get_movie_poster.assert_not_called()


def test_movie_swallows_store_exception():
    store = Mock(spec=MediaDataStore)
    store.get_movie_poster.side_effect = RuntimeError("disk error")

    np = _movie()
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    assert np.images == []


def test_no_op_without_artist_or_album():
    store = Mock(spec=MediaDataStore)
    np = _song(subtitle="", album="")
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)
    assert np.images == []
    store.get_artist_photo.assert_not_called()
    store.get_album_art.assert_not_called()


def test_no_op_on_album_art_without_album():
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.return_value = None

    np = _song(album="")
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    store.get_artist_photo.assert_called_once_with("Pink Floyd")
    store.get_album_art.assert_not_called()
    assert np.images == []


def test_swallows_store_exception():
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.return_value = None
    store.get_album_art.side_effect = RuntimeError("disk error")

    np = _song()
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    assert np.images == []


# ---------------------------------------------------------------------------
# Artist photo (music)
# ---------------------------------------------------------------------------

def test_adds_artist_photo_on_hit(tmp_path):
    store = Mock(spec=MediaDataStore)
    photo_path = tmp_path / "artist.jpg"
    photo_path.write_bytes(b"fake")
    store.get_artist_photo.return_value = photo_path
    store.get_album_art.return_value = None

    np = _song()
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    store.get_artist_photo.assert_called_once_with("Pink Floyd")
    assert len(np.images) == 1
    assert np.images[0].url == f"file://{photo_path}"
    assert "mediadata" in np.images[0].label.lower()
    assert np.images[0].is_artist_photo is True


def test_artist_photo_and_album_art_both_added(tmp_path):
    store = Mock(spec=MediaDataStore)
    photo_path = tmp_path / "artist.jpg"
    photo_path.write_bytes(b"fake")
    art_path = tmp_path / "albumart.jpg"
    art_path.write_bytes(b"fake")
    store.get_artist_photo.return_value = photo_path
    store.get_album_art.return_value = art_path

    np = _song()
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    urls = {img.url for img in np.images}
    assert urls == {f"file://{photo_path}", f"file://{art_path}"}
    by_url = {img.url: img for img in np.images}
    assert by_url[f"file://{photo_path}"].is_artist_photo is True
    assert by_url[f"file://{art_path}"].is_artist_photo is False


def test_artist_photo_fetched_even_without_known_album(tmp_path):
    store = Mock(spec=MediaDataStore)
    photo_path = tmp_path / "artist.jpg"
    photo_path.write_bytes(b"fake")
    store.get_artist_photo.return_value = photo_path

    np = _song(album="")
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    assert len(np.images) == 1
    assert np.images[0].is_artist_photo is True
    store.get_album_art.assert_not_called()


def test_no_op_when_artist_photo_store_misses(tmp_path):
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.return_value = None
    art_path = tmp_path / "albumart.jpg"
    art_path.write_bytes(b"fake")
    store.get_album_art.return_value = art_path

    np = _song()
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    assert len(np.images) == 1
    assert np.images[0].is_artist_photo is False


def test_swallows_artist_photo_store_exception():
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.side_effect = RuntimeError("disk error")

    np = _song()
    MediaDataArtworkEnricher(config=_config(), store=store).enrich(np)

    assert np.images == []
    # Artist photo is fetched before album art within one try/except (see
    # enrich()), so a raise here aborts the rest of _enrich_music for this
    # tick - album art is simply retried on the next tick, same as any
    # other _safe_call-isolated enricher failure.
    store.get_album_art.assert_not_called()


# ---------------------------------------------------------------------------
# Lyrics word cloud (music) - behind its own config.wordcloud.enabled
# switch, independent of the enricher's own `enabled`.
# ---------------------------------------------------------------------------

def test_adds_wordcloud_when_enabled(tmp_path):
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.return_value = None
    art_path = tmp_path / "albumart.jpg"
    art_path.write_bytes(b"fake")
    store.get_album_art.return_value = art_path
    wordcloud_path = tmp_path / "wordcloud.png"
    wordcloud_path.write_bytes(b"fake-png")
    store.get_track_wordcloud.return_value = wordcloud_path

    np = _song()
    MediaDataArtworkEnricher(config=_config(wordcloud_enabled=True), store=store).enrich(np)

    store.get_track_wordcloud.assert_called_once_with(
        "Pink Floyd", "The Wall", "Comfortably Numb", None
    )
    by_url = {img.url: img for img in np.images}
    assert by_url[f"file://{wordcloud_path}"].is_wordcloud is True
    assert "mediadata" in by_url[f"file://{wordcloud_path}"].label.lower()


def test_does_not_check_wordcloud_when_disabled(tmp_path):
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.return_value = None
    art_path = tmp_path / "albumart.jpg"
    art_path.write_bytes(b"fake")
    store.get_album_art.return_value = art_path

    np = _song()
    MediaDataArtworkEnricher(config=_config(wordcloud_enabled=False), store=store).enrich(np)

    store.get_track_wordcloud.assert_not_called()
    assert all(not img.is_wordcloud for img in np.images)


def test_no_op_on_wordcloud_store_miss(tmp_path):
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.return_value = None
    art_path = tmp_path / "albumart.jpg"
    art_path.write_bytes(b"fake")
    store.get_album_art.return_value = art_path
    store.get_track_wordcloud.return_value = None

    np = _song()
    MediaDataArtworkEnricher(config=_config(wordcloud_enabled=True), store=store).enrich(np)

    assert all(not img.is_wordcloud for img in np.images)


def test_wordcloud_not_checked_without_title(tmp_path):
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.return_value = None
    art_path = tmp_path / "albumart.jpg"
    art_path.write_bytes(b"fake")
    store.get_album_art.return_value = art_path

    np = _song(title="")
    MediaDataArtworkEnricher(config=_config(wordcloud_enabled=True), store=store).enrich(np)

    store.get_track_wordcloud.assert_not_called()


def test_wordcloud_not_checked_without_album(tmp_path):
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.return_value = None

    np = _song(album="")
    MediaDataArtworkEnricher(config=_config(wordcloud_enabled=True), store=store).enrich(np)

    store.get_track_wordcloud.assert_not_called()


def test_swallows_wordcloud_store_exception(tmp_path):
    store = Mock(spec=MediaDataStore)
    store.get_artist_photo.return_value = None
    art_path = tmp_path / "albumart.jpg"
    art_path.write_bytes(b"fake")
    store.get_album_art.return_value = art_path
    store.get_track_wordcloud.side_effect = RuntimeError("render error")

    np = _song()
    MediaDataArtworkEnricher(config=_config(wordcloud_enabled=True), store=store).enrich(np)

    assert all(not img.is_wordcloud for img in np.images)


# ---------------------------------------------------------------------------
# MediaDataWordcloudConfig validation (pydantic dataclass)
# ---------------------------------------------------------------------------

def test_wordcloud_config_unknown_field_raises_validation_error():
    import pytest

    with pytest.raises(ValueError, match="no_such_field"):
        MediaDataWordcloudConfig(no_such_field="x")


def test_wordcloud_config_disabled_by_default():
    assert MediaDataArtworkEnricherConfig().wordcloud.enabled is False
