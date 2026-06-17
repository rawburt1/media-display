"""Feed output: serves an RSS 2.0 and Atom 1.0 feed of recently played items.

Each item that starts playing becomes a new feed entry with title, description,
artwork URL (as an enclosure), and timestamp.  Idle gaps are not recorded.
The feed is held in memory and trimmed to the most recent `max_items` entries.

Endpoints served on the configured port:

  /rss    — RSS 2.0  (application/rss+xml)
  /atom   — Atom 1.0 (application/atom+xml)
  /       — simple HTML discovery page
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import List, Optional, Tuple
from xml.etree import ElementTree as ET

from flask import Flask, make_response, request

from pixoo_media.cache import ImageCache
from pixoo_media.config import FeedConfig
from pixoo_media.models import Artwork, NowPlaying
from pixoo_media.outputs.base import Output

logger = logging.getLogger(__name__)

_ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("", _ATOM_NS)

_INDEX_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Now Playing Feed</title></head>
<body>
<h1>Now Playing Feed</h1>
<ul>
  <li><a href="/rss">RSS 2.0</a></li>
  <li><a href="/atom">Atom 1.0</a></li>
</ul>
</body>
</html>"""


def _a(tag: str) -> str:
    """Clark-notation Atom tag name."""
    return f"{{{_ATOM_NS}}}{tag}"


def _image_mime(url: str) -> str:
    lower = url.lower().split("?")[0]
    for ext, mime in [(".png", "image/png"), (".webp", "image/webp"), (".gif", "image/gif")]:
        if lower.endswith(ext):
            return mime
    return "image/jpeg"


@dataclasses.dataclass
class _Entry:
    identity: tuple
    title: str
    description: str
    image_url: Optional[str]
    guid: str
    published: datetime


class FeedOutput(Output):
    handles_images = False

    def __init__(self, config: FeedConfig):
        self.config = config
        self._entries: List[_Entry] = []
        self._lock = threading.Lock()
        self.app = self._build_app()
        threading.Thread(target=self._run_server, daemon=True).start()

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        pass

    def on_idle(self) -> None:
        pass

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        entry = self._make_entry(now_playing)
        with self._lock:
            # Skip if the same item is re-detected without an intervening change.
            if self._entries and self._entries[0].identity == entry.identity:
                return
            self._entries.insert(0, entry)
            del self._entries[self.config.max_items:]

    def _make_entry(self, np: NowPlaying) -> _Entry:
        now = datetime.now(tz=timezone.utc)
        feed_title, description = self._format(np)
        image_url = next((img.url for img in np.images if img.url), None)
        guid = f"{np.source}:{np.title}:{np.subtitle}:{now.timestamp():.0f}"
        return _Entry(
            identity=np.identity,
            title=feed_title,
            description=description,
            image_url=image_url,
            guid=guid,
            published=now,
        )

    @staticmethod
    def _format(np: NowPlaying) -> Tuple[str, str]:
        if np.media_type == "music":
            title = f"{np.subtitle} – {np.title}" if np.subtitle else np.title
            desc = f"Album: {np.album}" if np.album else ""
            return title, desc
        if np.media_type == "movie":
            title = f"{np.title} ({np.year})" if np.year else np.title
            return title, ""
        if np.media_type == "episode":
            title = f"{np.title} – {np.subtitle}" if np.subtitle else np.title
            return title, ""
        return np.title, np.subtitle

    def _run_server(self) -> None:
        logger.info("Starting feed server on %s:%s", self.config.host, self.config.port)
        self.app.run(host=self.config.host, port=self.config.port, threaded=True)

    def _build_app(self) -> Flask:
        app = Flask(__name__)

        @app.get("/")
        def index():
            return _INDEX_HTML

        @app.get("/rss")
        def rss():
            with self._lock:
                entries = list(self._entries)
            resp = make_response(self._build_rss(entries, request.host_url))
            resp.content_type = "application/rss+xml; charset=utf-8"
            return resp

        @app.get("/atom")
        def atom():
            with self._lock:
                entries = list(self._entries)
            resp = make_response(self._build_atom(entries, request.host_url))
            resp.content_type = "application/atom+xml; charset=utf-8"
            return resp

        return app

    def _build_rss(self, entries: List[_Entry], base_url: str) -> str:
        rss = ET.Element("rss", version="2.0")
        ch = ET.SubElement(rss, "channel")
        ET.SubElement(ch, "title").text = self.config.title
        ET.SubElement(ch, "link").text = base_url
        ET.SubElement(ch, "description").text = "Recently played media"
        if entries:
            ET.SubElement(ch, "lastBuildDate").text = format_datetime(entries[0].published)
        for e in entries:
            item = ET.SubElement(ch, "item")
            ET.SubElement(item, "title").text = e.title
            if e.description:
                ET.SubElement(item, "description").text = e.description
            ET.SubElement(item, "pubDate").text = format_datetime(e.published)
            ET.SubElement(item, "guid", isPermaLink="false").text = e.guid
            if e.image_url:
                ET.SubElement(
                    item, "enclosure",
                    url=e.image_url,
                    type=_image_mime(e.image_url),
                    length="0",
                )
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode")

    def _build_atom(self, entries: List[_Entry], base_url: str) -> str:
        feed = ET.Element(_a("feed"))
        ET.SubElement(feed, _a("title")).text = self.config.title
        ET.SubElement(feed, _a("id")).text = f"urn:pixoo-media:feed:{self.config.port}"
        ET.SubElement(feed, _a("link"), href=base_url, rel="alternate")
        updated = entries[0].published.isoformat() if entries else datetime.now(tz=timezone.utc).isoformat()
        ET.SubElement(feed, _a("updated")).text = updated
        for e in entries:
            entry = ET.SubElement(feed, _a("entry"))
            ET.SubElement(entry, _a("title")).text = e.title
            ET.SubElement(entry, _a("id")).text = f"urn:pixoo-media:{e.guid}"
            ET.SubElement(entry, _a("updated")).text = e.published.isoformat()
            if e.description:
                ET.SubElement(entry, _a("summary")).text = e.description
            if e.image_url:
                ET.SubElement(
                    entry, _a("link"),
                    rel="enclosure",
                    href=e.image_url,
                    type=_image_mime(e.image_url),
                )
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(feed, encoding="unicode")
