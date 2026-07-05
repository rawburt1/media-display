"""Tests for TextCache."""

import os
import time

from mediainfo.text_cache import TextCache


def test_get_returns_none_for_missing_entry(tmp_path):
    cache = TextCache(tmp_path)
    assert cache.get("lrclib", "queen - bohemian rhapsody") is None


def test_set_then_get_round_trips_json_value(tmp_path):
    cache = TextCache(tmp_path)
    cache.set("lrclib", "queen - bohemian rhapsody", {"lyrics": "Is this the real life"})
    assert cache.get("lrclib", "queen - bohemian rhapsody") == {
        "lyrics": "Is this the real life"
    }


def test_different_namespaces_do_not_collide(tmp_path):
    cache = TextCache(tmp_path)
    cache.set("lrclib", "same-key", {"source": "lrclib"})
    cache.set("ollama_text", "same-key", {"source": "ollama"})

    assert cache.get("lrclib", "same-key") == {"source": "lrclib"}
    assert cache.get("ollama_text", "same-key") == {"source": "ollama"}


def test_get_returns_none_past_max_age(tmp_path):
    cache = TextCache(tmp_path, max_age_days=1)
    cache.set("lrclib", "old-song", {"lyrics": "..."})

    path = cache._path_for("lrclib", "old-song")
    old_time = time.time() - (2 * 86400)
    os.utime(path, (old_time, old_time))

    assert cache.get("lrclib", "old-song") is None


def test_get_returns_none_for_corrupt_entry(tmp_path):
    cache = TextCache(tmp_path)
    path = cache._path_for("lrclib", "bad-song")
    path.write_text("not valid json{{{", encoding="utf-8")

    assert cache.get("lrclib", "bad-song") is None


def test_purge_expired_removes_only_old_entries(tmp_path):
    cache = TextCache(tmp_path, max_age_days=1)
    cache.set("lrclib", "fresh-song", {"lyrics": "new"})
    cache.set("lrclib", "old-song", {"lyrics": "old"})

    old_path = cache._path_for("lrclib", "old-song")
    old_time = time.time() - (2 * 86400)
    os.utime(old_path, (old_time, old_time))

    cache.purge_expired()

    assert cache.get("lrclib", "fresh-song") == {"lyrics": "new"}
    assert not old_path.exists()
