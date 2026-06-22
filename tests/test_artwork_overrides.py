"""Tests for ArtworkOverrideStore."""

from pathlib import Path
from urllib.parse import urlparse

from mediainfo.artwork_overrides import ArtworkOverrideStore


def _path_for(artwork) -> Path:
    return Path(urlparse(artwork.url).path)


def test_get_returns_none_when_no_override(tmp_path):
    store = ArtworkOverrideStore(str(tmp_path))
    assert store.get("Inception", "") is None


def test_set_then_get_returns_file_url(tmp_path):
    store = ArtworkOverrideStore(str(tmp_path))
    store.set("Inception", "", b"fake-image-bytes")

    artwork = store.get("Inception", "")

    assert artwork is not None
    assert artwork.url.startswith("file://")
    assert artwork.label == "Manual override"


def test_match_is_case_insensitive_and_trims_whitespace(tmp_path):
    store = ArtworkOverrideStore(str(tmp_path))
    store.set(" Inception ", " ", b"fake-image-bytes")

    assert store.get("inception", "") is not None
    assert store.get("INCEPTION", "  ") is not None


def test_title_and_subtitle_both_match(tmp_path):
    store = ArtworkOverrideStore(str(tmp_path))
    store.set("Bohemian Rhapsody", "Queen", b"fake-image-bytes")

    assert store.get("Bohemian Rhapsody", "Queen") is not None
    assert store.get("Bohemian Rhapsody", "Someone Else") is None


def test_stored_file_actually_exists_on_disk(tmp_path):
    store = ArtworkOverrideStore(str(tmp_path))
    store.set("Inception", "", b"fake-image-bytes")

    path = _path_for(store.get("Inception", ""))
    assert path.exists()
    assert path.read_bytes() == b"fake-image-bytes"


def test_set_again_replaces_previous_file(tmp_path):
    store = ArtworkOverrideStore(str(tmp_path))
    store.set("Inception", "", b"first")
    first = store.get("Inception", "")

    store.set("Inception", "", b"second")
    second = store.get("Inception", "")

    assert first.url != second.url
    assert not _path_for(first).exists()  # old file removed
    assert _path_for(second).read_bytes() == b"second"


def test_remove_returns_true_and_deletes_file(tmp_path):
    store = ArtworkOverrideStore(str(tmp_path))
    store.set("Inception", "", b"fake-image-bytes")
    artwork = store.get("Inception", "")

    removed = store.remove("Inception", "")

    assert removed is True
    assert store.get("Inception", "") is None
    assert not _path_for(artwork).exists()


def test_remove_returns_false_when_nothing_to_remove(tmp_path):
    store = ArtworkOverrideStore(str(tmp_path))
    assert store.remove("Inception", "") is False


def test_list_returns_all_entries(tmp_path):
    store = ArtworkOverrideStore(str(tmp_path))
    store.set("Inception", "", b"a")
    store.set("Bohemian Rhapsody", "Queen", b"b")

    items = store.list()

    titles = {item["title"] for item in items}
    assert titles == {"Inception", "Bohemian Rhapsody"}


def test_get_returns_none_if_underlying_file_missing(tmp_path):
    store = ArtworkOverrideStore(str(tmp_path))
    store.set("Inception", "", b"fake-image-bytes")
    artwork = store.get("Inception", "")
    _path_for(artwork).unlink()

    assert store.get("Inception", "") is None


def test_index_persists_across_store_instances(tmp_path):
    store1 = ArtworkOverrideStore(str(tmp_path))
    store1.set("Inception", "", b"fake-image-bytes")

    store2 = ArtworkOverrideStore(str(tmp_path))

    assert store2.get("Inception", "") is not None


def test_directory_created_on_init(tmp_path):
    target = tmp_path / "nested" / "overrides"
    ArtworkOverrideStore(str(target))
    assert target.is_dir()
