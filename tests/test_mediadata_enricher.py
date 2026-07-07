"""Tests for the MediaDataStore-backed album art enricher."""

from unittest.mock import Mock

from mediainfo.enrichers.mediadata import MediaDataArtworkEnricher
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying


def _song(**kwargs):
    defaults = dict(
        source="youtube", media_type="music",
        title="Comfortably Numb", subtitle="Pink Floyd", album="The Wall",
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def test_adds_album_art_on_hit(tmp_path):
    store = Mock(spec=MediaDataStore)
    art_path = tmp_path / "albumart.jpg"
    art_path.write_bytes(b"fake")
    store.get_album_art.return_value = art_path

    np = _song()
    MediaDataArtworkEnricher(config=object(), store=store).enrich(np)

    store.get_album_art.assert_called_once_with("Pink Floyd", "The Wall", None)
    assert len(np.images) == 1
    assert np.images[0].url == f"file://{art_path}"
    assert "mediadata" in np.images[0].label.lower()


def test_does_not_replace_existing_images(tmp_path):
    store = Mock(spec=MediaDataStore)
    art_path = tmp_path / "albumart.jpg"
    art_path.write_bytes(b"fake")
    store.get_album_art.return_value = art_path

    np = _song(images=[Artwork(url="https://example.com/existing.jpg", label="existing")])
    MediaDataArtworkEnricher(config=object(), store=store).enrich(np)

    assert len(np.images) == 2
    urls = {img.url for img in np.images}
    assert urls == {"https://example.com/existing.jpg", f"file://{art_path}"}


def test_does_not_add_duplicate_url(tmp_path):
    store = Mock(spec=MediaDataStore)
    art_path = tmp_path / "albumart.jpg"
    art_path.write_bytes(b"fake")
    store.get_album_art.return_value = art_path

    np = _song(images=[Artwork(url=f"file://{art_path}", label="existing")])
    MediaDataArtworkEnricher(config=object(), store=store).enrich(np)

    assert len(np.images) == 1


def test_no_op_on_store_miss():
    store = Mock(spec=MediaDataStore)
    store.get_album_art.return_value = None

    np = _song()
    MediaDataArtworkEnricher(config=object(), store=store).enrich(np)

    assert np.images == []


def test_no_op_when_store_is_none():
    np = _song()
    MediaDataArtworkEnricher(config=object(), store=None).enrich(np)
    assert np.images == []


def test_no_op_for_non_music():
    store = Mock(spec=MediaDataStore)
    np = _song(media_type="movie")
    MediaDataArtworkEnricher(config=object(), store=store).enrich(np)
    assert np.images == []
    store.get_album_art.assert_not_called()


def test_no_op_without_artist_or_album():
    store = Mock(spec=MediaDataStore)
    np = _song(subtitle="", album="")
    MediaDataArtworkEnricher(config=object(), store=store).enrich(np)
    assert np.images == []
    store.get_album_art.assert_not_called()


def test_swallows_store_exception():
    store = Mock(spec=MediaDataStore)
    store.get_album_art.side_effect = RuntimeError("disk error")

    np = _song()
    MediaDataArtworkEnricher(config=object(), store=store).enrich(np)

    assert np.images == []
