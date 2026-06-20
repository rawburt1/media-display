"""Tests for the folder output (mirrors current artwork to a local folder)."""

from unittest.mock import MagicMock

from mediainfo.config import FolderConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.folder import FolderOutput


def _now_playing(images, source="kodi"):
    return NowPlaying(source=source, media_type="movie", title="Inception", images=images)


def test_on_new_item_copies_all_images(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    poster = src_dir / "abc123.jpg"
    poster.write_bytes(b"poster-bytes")
    fanart = src_dir / "def456.png"
    fanart.write_bytes(b"fanart-bytes")

    artworks = [
        Artwork(url="https://example.com/poster.jpg", label="Poster (fanart.tv)"),
        Artwork(url="https://example.com/fanart.png", label="Fanart (fanart.tv)"),
    ]
    cache = MagicMock()
    cache.get_path.side_effect = [poster, fanart]
    cache.get_transformed_path.side_effect = lambda path, _: path

    out_dir = tmp_path / "artwork"
    output = FolderOutput(FolderConfig(enabled=True, dir=str(out_dir)))
    output.on_new_item(_now_playing(artworks), cache)

    assert (out_dir / "Poster (fanart.tv).jpg").read_bytes() == b"poster-bytes"
    assert (out_dir / "Fanart (fanart.tv).png").read_bytes() == b"fanart-bytes"
    assert len(list(out_dir.iterdir())) == 2


def test_on_new_item_clears_previous_contents(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    poster = src_dir / "abc123.jpg"
    poster.write_bytes(b"new-poster")

    out_dir = tmp_path / "artwork"
    out_dir.mkdir()
    (out_dir / "stale.jpg").write_bytes(b"stale")

    cache = MagicMock()
    cache.get_path.return_value = poster
    cache.get_transformed_path.side_effect = lambda path, _: path

    output = FolderOutput(FolderConfig(enabled=True, dir=str(out_dir)))
    output.on_new_item(
        _now_playing([Artwork(url="https://example.com/p.jpg", label="Poster (fanart.tv)")]),
        cache,
    )

    files = list(out_dir.iterdir())
    assert (out_dir / "stale.jpg") not in files
    assert (out_dir / "Poster (fanart.tv).jpg").read_bytes() == b"new-poster"


def test_on_new_item_skips_artwork_with_no_cached_path(tmp_path):
    out_dir = tmp_path / "artwork"
    cache = MagicMock()
    cache.get_path.return_value = None

    output = FolderOutput(FolderConfig(enabled=True, dir=str(out_dir)))
    output.on_new_item(
        _now_playing([Artwork(url="", label="Poster (fanart.tv)")]),
        cache,
    )

    assert list(out_dir.iterdir()) == []


def test_on_idle_clears_folder(tmp_path):
    out_dir = tmp_path / "artwork"
    out_dir.mkdir()
    (out_dir / "old.jpg").write_bytes(b"old")

    output = FolderOutput(FolderConfig(enabled=True, dir=str(out_dir)))
    output.on_idle()

    assert list(out_dir.iterdir()) == []


def test_update_with_idle_now_playing_does_not_modify_folder(tmp_path):
    out_dir = tmp_path / "artwork"
    out_dir.mkdir()
    (out_dir / "old.jpg").write_bytes(b"old")

    output = FolderOutput(FolderConfig(enabled=True, dir=str(out_dir)))
    idle_now_playing = NowPlaying(source="idle", media_type="wallpaper", title="", subtitle="")
    output.update(idle_now_playing, Artwork(url="https://example.com/w.jpg"), tmp_path / "w.jpg")

    assert (out_dir / "old.jpg").read_bytes() == b"old"


def test_on_new_item_with_idle_batch_copies_all_wallpapers(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    wallpaper_a = src_dir / "a.jpg"
    wallpaper_a.write_bytes(b"wallpaper-a")
    wallpaper_b = src_dir / "b.jpg"
    wallpaper_b.write_bytes(b"wallpaper-b")

    wallpapers = [
        Artwork(url="https://example.com/a.jpg", label="A"),
        Artwork(url="https://example.com/b.jpg", label="B"),
    ]
    cache = MagicMock()
    cache.get_path.side_effect = [wallpaper_a, wallpaper_b]
    cache.get_transformed_path.side_effect = lambda path, _: path

    out_dir = tmp_path / "artwork"
    output = FolderOutput(FolderConfig(enabled=True, dir=str(out_dir)))
    idle_now_playing = NowPlaying(
        source="idle", media_type="wallpaper", title="", subtitle="", images=wallpapers
    )
    output.on_new_item(idle_now_playing, cache)

    assert (out_dir / "A.jpg").read_bytes() == b"wallpaper-a"
    assert (out_dir / "B.jpg").read_bytes() == b"wallpaper-b"
    cache.get_path.assert_any_call(wallpapers[0], idle=True)
    cache.get_path.assert_any_call(wallpapers[1], idle=True)


def test_update_with_non_idle_now_playing_does_not_modify_folder(tmp_path):
    out_dir = tmp_path / "artwork"
    out_dir.mkdir()
    (out_dir / "current.jpg").write_bytes(b"current")

    output = FolderOutput(FolderConfig(enabled=True, dir=str(out_dir)))
    output.update(
        _now_playing([]), Artwork(url="https://example.com/p.jpg"), tmp_path / "p.jpg"
    )

    assert (out_dir / "current.jpg").read_bytes() == b"current"


def test_sanitizes_label_for_filename(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    image = src_dir / "abc.jpg"
    image.write_bytes(b"image-bytes")

    cache = MagicMock()
    cache.get_path.return_value = image
    cache.get_transformed_path.side_effect = lambda path, _: path

    out_dir = tmp_path / "artwork"
    output = FolderOutput(FolderConfig(enabled=True, dir=str(out_dir)))
    output.on_new_item(
        _now_playing([Artwork(url="https://example.com/i.jpg", label="Season 1/2 poster")]),
        cache,
    )

    files = list(out_dir.iterdir())
    assert len(files) == 1
    assert "/" not in files[0].name
    assert files[0].read_bytes() == b"image-bytes"
