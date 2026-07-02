"""Tests for the playback history store (history.py)."""

from unittest.mock import patch

from mediainfo.history import PlaybackHistory
from mediainfo.models import Artwork, NowPlaying


def _store(tmp_path, **kwargs):
    return PlaybackHistory(str(tmp_path / "history.db"), **kwargs)


def _item(title="Aja", subtitle="Steely Dan", source="sonos", media_type="music", images=None):
    return NowPlaying(
        source=source, media_type=media_type, title=title, subtitle=subtitle,
        album="Aja", images=images if images is not None else [],
    )


def test_record_and_list_newest_first(tmp_path):
    store = _store(tmp_path)
    with patch("mediainfo.history.time.time", side_effect=[1000.0, 2000.0]):
        store.record(_item(title="First"))
        store.record(_item(title="Second"))

    items = store.list()
    assert [i["title"] for i in items] == ["Second", "First"]
    assert items[0]["source"] == "sonos"
    assert items[0]["media_type"] == "music"
    assert items[0]["subtitle"] == "Steely Dan"
    assert items[0]["played_at"] == 2000.0


def test_prefers_non_artist_photo_artwork(tmp_path):
    store = _store(tmp_path)
    store.record(_item(images=[
        Artwork(url="http://x/bio.jpg", is_artist_photo=True),
        Artwork(url="http://x/cover.jpg"),
    ]))

    entry_id = store.list()[0]["id"]
    assert store.entry_artwork(entry_id) == ("http://x/cover.jpg", "music")


def test_entry_without_artwork(tmp_path):
    store = _store(tmp_path)
    store.record(_item(images=[]))
    items = store.list()
    assert items[0]["has_artwork"] is False
    assert store.entry_artwork(items[0]["id"]) is None


def test_repeat_within_dedupe_window_is_skipped(tmp_path):
    store = _store(tmp_path, dedupe_window_seconds=600)
    with patch("mediainfo.history.time.time", side_effect=[1000.0, 1300.0, 2000.0]):
        store.record(_item())
        store.record(_item())  # 300s later: same item, skipped
        store.record(_item())  # 1000s later: logged again (genuine replay)

    assert len(store.list()) == 2


def test_different_item_within_window_is_logged(tmp_path):
    store = _store(tmp_path, dedupe_window_seconds=600)
    with patch("mediainfo.history.time.time", side_effect=[1000.0, 1010.0]):
        store.record(_item(title="One"))
        store.record(_item(title="Two"))

    assert len(store.list()) == 2


def test_prunes_oldest_beyond_max_entries(tmp_path):
    store = _store(tmp_path, max_entries=3, dedupe_window_seconds=0)
    times = iter(float(i) for i in range(1000, 1010))
    with patch("mediainfo.history.time.time", lambda: next(times)):
        for i in range(5):
            store.record(_item(title=f"Song {i}"))

    titles = [i["title"] for i in store.list()]
    assert titles == ["Song 4", "Song 3", "Song 2"]


def test_persists_across_reopen(tmp_path):
    store = _store(tmp_path)
    store.record(_item())
    store.close()

    reopened = _store(tmp_path)
    assert len(reopened.list()) == 1


def test_record_never_raises(tmp_path):
    store = _store(tmp_path)
    store.close()  # closed connection: _record will fail internally
    store.record(_item())  # must not raise


def test_list_limit_clamped(tmp_path):
    store = _store(tmp_path, dedupe_window_seconds=0)
    for i in range(5):
        store.record(_item(title=f"Song {i}"))
    assert len(store.list(limit=2)) == 2
    assert len(store.list(limit=0)) == 1  # clamped to at least 1
