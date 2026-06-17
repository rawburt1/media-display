"""Tests for the RSS/Atom feed output."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from xml.etree import ElementTree as ET

import pytest

from pixoo_media.config import FeedConfig
from pixoo_media.models import Artwork, NowPlaying
from pixoo_media.outputs.feeds import FeedOutput, _image_mime

_ATOM_NS = "http://www.w3.org/2005/Atom"


def _a(tag):
    return f"{{{_ATOM_NS}}}{tag}"


def _config(**kwargs):
    defaults = dict(enabled=True, host="127.0.0.1", port=8086, title="Now Playing", max_items=10)
    defaults.update(kwargs)
    return FeedConfig(**defaults)


def _music(title="Bohemian Rhapsody", artist="Queen", album="A Night at the Opera", images=None):
    return NowPlaying(
        source="kodi",
        media_type="music",
        title=title,
        subtitle=artist,
        album=album,
        images=images or [],
    )


def _movie(title="Inception", year=2010):
    return NowPlaying(source="kodi", media_type="movie", title=title, year=year, images=[])


def _episode(show="Breaking Bad", subtitle="S01E01 – Pilot"):
    return NowPlaying(source="kodi", media_type="episode", title=show, subtitle=subtitle, images=[])


@pytest.fixture(autouse=True)
def no_server(monkeypatch):
    monkeypatch.setattr("threading.Thread.start", lambda self: None)


def _output(**kwargs):
    return FeedOutput(_config(**kwargs))


# ---------------------------------------------------------------------------
# _format
# ---------------------------------------------------------------------------

def test_format_music_with_artist_and_album():
    title, desc = FeedOutput._format(_music())
    assert title == "Queen – Bohemian Rhapsody"
    assert desc == "Album: A Night at the Opera"


def test_format_music_no_album():
    np = NowPlaying(source="kodi", media_type="music", title="Track", subtitle="Artist", images=[])
    title, desc = FeedOutput._format(np)
    assert title == "Artist – Track"
    assert desc == ""


def test_format_music_no_artist():
    np = NowPlaying(source="kodi", media_type="music", title="Track", subtitle="", images=[])
    title, desc = FeedOutput._format(np)
    assert title == "Track"


def test_format_movie_with_year():
    title, desc = FeedOutput._format(_movie())
    assert title == "Inception (2010)"
    assert desc == ""


def test_format_movie_without_year():
    np = NowPlaying(source="kodi", media_type="movie", title="Inception", images=[])
    title, _ = FeedOutput._format(np)
    assert title == "Inception"


def test_format_episode():
    title, desc = FeedOutput._format(_episode())
    assert title == "Breaking Bad – S01E01 – Pilot"
    assert desc == ""


# ---------------------------------------------------------------------------
# on_new_item
# ---------------------------------------------------------------------------

def test_on_new_item_adds_entry():
    out = _output()
    out.on_new_item(_music(), MagicMock())
    assert len(out._entries) == 1
    assert out._entries[0].title == "Queen – Bohemian Rhapsody"


def test_on_new_item_prepends_most_recent():
    out = _output()
    out.on_new_item(_music(title="Song A"), MagicMock())
    out.on_new_item(_music(title="Song B"), MagicMock())
    assert out._entries[0].title.endswith("Song B")
    assert out._entries[1].title.endswith("Song A")


def test_on_new_item_skips_duplicate_identity():
    out = _output()
    out.on_new_item(_music(), MagicMock())
    out.on_new_item(_music(), MagicMock())
    assert len(out._entries) == 1


def test_on_new_item_same_song_twice_after_different_adds_two_entries():
    out = _output()
    out.on_new_item(_music(title="Song A"), MagicMock())
    out.on_new_item(_music(title="Song B"), MagicMock())
    out.on_new_item(_music(title="Song A"), MagicMock())
    assert len(out._entries) == 3


def test_on_new_item_trims_to_max_items():
    out = _output(max_items=3)
    for i in range(5):
        out.on_new_item(_music(title=f"Song {i}", artist=f"Artist {i}"), MagicMock())
    assert len(out._entries) == 3
    assert out._entries[0].title == "Artist 4 – Song 4"


def test_on_new_item_captures_image_url():
    art = Artwork(url="https://example.com/cover.jpg", label="Cover")
    np = _music(images=[art])
    out = _output()
    out.on_new_item(np, MagicMock())
    assert out._entries[0].image_url == "https://example.com/cover.jpg"


def test_on_new_item_no_image_when_images_empty():
    out = _output()
    out.on_new_item(_music(images=[]), MagicMock())
    assert out._entries[0].image_url is None


def test_on_new_item_skips_blank_image_url():
    art = Artwork(url="", label="Cover")
    out = _output()
    out.on_new_item(_music(images=[art]), MagicMock())
    assert out._entries[0].image_url is None


def test_on_idle_is_noop():
    out = _output()
    out.on_new_item(_music(), MagicMock())
    out.on_idle()
    assert len(out._entries) == 1


def test_update_is_noop():
    out = _output()
    out.on_new_item(_music(), MagicMock())
    out.update(_music(), Artwork(url=""), "/tmp/a.jpg")
    assert len(out._entries) == 1


# ---------------------------------------------------------------------------
# _image_mime
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://example.com/cover.jpg", "image/jpeg"),
    ("https://example.com/cover.JPEG", "image/jpeg"),
    ("https://example.com/cover.png", "image/png"),
    ("https://example.com/cover.webp", "image/webp"),
    ("https://example.com/cover.gif", "image/gif"),
    ("https://example.com/cover.png?v=123", "image/png"),
    ("https://example.com/image", "image/jpeg"),  # unknown → jpeg
])
def test_image_mime(url, expected):
    assert _image_mime(url) == expected


# ---------------------------------------------------------------------------
# RSS XML structure
# ---------------------------------------------------------------------------

def test_rss_endpoint_returns_xml_with_correct_content_type():
    out = _output()
    out.on_new_item(_music(), MagicMock())
    with out.app.test_client() as client:
        resp = client.get("/rss")
    assert resp.status_code == 200
    assert "application/rss+xml" in resp.content_type


def test_rss_channel_title():
    out = _output(title="My Music Feed")
    with out.app.test_client() as client:
        resp = client.get("/rss")
    root = ET.fromstring(resp.data)
    assert root.find("channel/title").text == "My Music Feed"


def test_rss_item_title_and_description():
    out = _output()
    out.on_new_item(_music(), MagicMock())
    with out.app.test_client() as client:
        root = ET.fromstring(client.get("/rss").data)
    item = root.find("channel/item")
    assert item.find("title").text == "Queen – Bohemian Rhapsody"
    assert item.find("description").text == "Album: A Night at the Opera"


def test_rss_item_guid_present():
    out = _output()
    out.on_new_item(_music(), MagicMock())
    with out.app.test_client() as client:
        root = ET.fromstring(client.get("/rss").data)
    guid = root.find("channel/item/guid")
    assert guid is not None
    assert guid.text
    assert guid.get("isPermaLink") == "false"


def test_rss_item_pub_date_present():
    out = _output()
    out.on_new_item(_music(), MagicMock())
    with out.app.test_client() as client:
        root = ET.fromstring(client.get("/rss").data)
    assert root.find("channel/item/pubDate").text


def test_rss_item_enclosure_when_image_present():
    art = Artwork(url="https://fanart.tv/cover.jpg", label="Cover")
    out = _output()
    out.on_new_item(_music(images=[art]), MagicMock())
    with out.app.test_client() as client:
        root = ET.fromstring(client.get("/rss").data)
    enc = root.find("channel/item/enclosure")
    assert enc is not None
    assert enc.get("url") == "https://fanart.tv/cover.jpg"
    assert enc.get("type") == "image/jpeg"
    assert enc.get("length") == "0"


def test_rss_no_enclosure_when_no_image():
    out = _output()
    out.on_new_item(_music(images=[]), MagicMock())
    with out.app.test_client() as client:
        root = ET.fromstring(client.get("/rss").data)
    assert root.find("channel/item/enclosure") is None


def test_rss_multiple_items_in_order():
    out = _output()
    out.on_new_item(_music(title="Song A", artist="Alpha"), MagicMock())
    out.on_new_item(_music(title="Song B", artist="Beta"), MagicMock())
    with out.app.test_client() as client:
        root = ET.fromstring(client.get("/rss").data)
    items = root.findall("channel/item")
    assert len(items) == 2
    assert "Song B" in items[0].find("title").text  # most recent first
    assert "Song A" in items[1].find("title").text


def test_rss_empty_feed_has_no_items():
    out = _output()
    with out.app.test_client() as client:
        root = ET.fromstring(client.get("/rss").data)
    assert root.findall("channel/item") == []


# ---------------------------------------------------------------------------
# Atom XML structure
# ---------------------------------------------------------------------------

def test_atom_endpoint_returns_xml_with_correct_content_type():
    out = _output()
    with out.app.test_client() as client:
        resp = client.get("/atom")
    assert resp.status_code == 200
    assert "application/atom+xml" in resp.content_type


def test_atom_feed_title():
    out = _output(title="My Stream")
    with out.app.test_client() as client:
        root = ET.fromstring(client.get("/atom").data)
    assert root.find(_a("title")).text == "My Stream"


def test_atom_feed_has_id():
    out = _output(port=8086)
    with out.app.test_client() as client:
        root = ET.fromstring(client.get("/atom").data)
    feed_id = root.find(_a("id")).text
    assert "8086" in feed_id


def test_atom_entry_title_and_summary():
    out = _output()
    out.on_new_item(_music(), MagicMock())
    with out.app.test_client() as client:
        root = ET.fromstring(client.get("/atom").data)
    entry = root.find(_a("entry"))
    assert entry.find(_a("title")).text == "Queen – Bohemian Rhapsody"
    assert entry.find(_a("summary")).text == "Album: A Night at the Opera"


def test_atom_entry_id_and_updated():
    out = _output()
    out.on_new_item(_music(), MagicMock())
    with out.app.test_client() as client:
        root = ET.fromstring(client.get("/atom").data)
    entry = root.find(_a("entry"))
    assert entry.find(_a("id")).text.startswith("urn:pixoo-media:")
    assert entry.find(_a("updated")).text


def test_atom_entry_enclosure_link():
    art = Artwork(url="https://fanart.tv/cover.png", label="Cover")
    out = _output()
    out.on_new_item(_music(images=[art]), MagicMock())
    with out.app.test_client() as client:
        root = ET.fromstring(client.get("/atom").data)
    links = root.find(_a("entry")).findall(_a("link"))
    enclosures = [l for l in links if l.get("rel") == "enclosure"]
    assert len(enclosures) == 1
    assert enclosures[0].get("href") == "https://fanart.tv/cover.png"
    assert enclosures[0].get("type") == "image/png"


def test_atom_no_summary_when_description_empty():
    out = _output()
    out.on_new_item(_movie(), MagicMock())
    with out.app.test_client() as client:
        root = ET.fromstring(client.get("/atom").data)
    assert root.find(_a("entry")).find(_a("summary")) is None


# ---------------------------------------------------------------------------
# HTML discovery page
# ---------------------------------------------------------------------------

def test_index_page_links_to_both_feeds():
    out = _output()
    with out.app.test_client() as client:
        resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "/rss" in body
    assert "/atom" in body
