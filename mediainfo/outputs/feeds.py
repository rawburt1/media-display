"""Feed output: serves an RSS 2.0 and Atom 1.0 feed describing only the
currently playing item.

The feed holds at most one entry - title, description, artwork URL (as an
enclosure), and timestamp - replaced whenever the playing item changes, and
cleared while idle (including while idle wallpapers are showing, which are
decorative and never themselves "now playing").

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

from flask import Blueprint, make_response, render_template, request

from mediainfo.cache import ImageCache
from mediainfo.config import FeedConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output

logger = logging.getLogger(__name__)

_ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("", _ATOM_NS)


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
        # Set by build_http_blueprint() once wiring.py has computed it -
        # used as a stable per-instance identifier (see _build_atom()),
        # replacing the old config.port-based one now that every instance
        # no longer has its own port.
        self._url_prefix = ""

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        pass

    def on_idle(self) -> None:
        with self._lock:
            self._entries = []

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        # Idle wallpaper batches go through on_new_item too (so outputs like
        # FolderOutput can mirror them), but they're decorative, not
        # "playing" - the feed should go empty for these, same as on_idle().
        if now_playing.source == "idle":
            with self._lock:
                self._entries = []
            return

        entry = self._make_entry(now_playing)
        with self._lock:
            # Skip if the same item is re-detected without an intervening change.
            if self._entries and self._entries[0].identity == entry.identity:
                return
            self._entries = [entry]

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
            parts = [f"Album: {np.album}"] if np.album else []
            if np.summary:
                parts.append(np.summary)
            return title, "\n\n".join(parts)
        if np.media_type == "movie":
            title = f"{np.title} ({np.year})" if np.year else np.title
            return title, np.summary
        if np.media_type == "episode":
            title = f"{np.title} – {np.subtitle}" if np.subtitle else np.title
            return title, np.summary
        return np.title, np.subtitle

    def build_http_blueprint(self, url_prefix: str, sock=None) -> Blueprint:
        self._url_prefix = url_prefix
        bp = Blueprint("feed", __name__)

        @bp.get("/")
        def index():
            return render_template("feeds/index.html")

        @bp.get("/rss")
        def rss():
            with self._lock:
                entries = list(self._entries)
            resp = make_response(self._build_rss(entries, request.host_url))
            resp.content_type = "application/rss+xml; charset=utf-8"
            return resp

        @bp.get("/atom")
        def atom():
            with self._lock:
                entries = list(self._entries)
            resp = make_response(self._build_atom(entries, request.host_url))
            resp.content_type = "application/atom+xml; charset=utf-8"
            return resp

        return bp

    def _build_rss(self, entries: List[_Entry], base_url: str) -> str:
        rss = ET.Element("rss", version="2.0")
        ch = ET.SubElement(rss, "channel")
        ET.SubElement(ch, "title").text = self.config.title
        ET.SubElement(ch, "link").text = base_url
        ET.SubElement(ch, "description").text = "Currently playing media"
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
                    item,
                    "enclosure",
                    url=e.image_url,
                    type=_image_mime(e.image_url),
                    length="0",
                )
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode")

    def _build_atom(self, entries: List[_Entry], base_url: str) -> str:
        feed = ET.Element(_a("feed"))
        ET.SubElement(feed, _a("title")).text = self.config.title
        ET.SubElement(feed, _a("id")).text = f"urn:mediainfo:feed:{self._url_prefix}"
        ET.SubElement(feed, _a("link"), href=base_url, rel="alternate")
        updated = (
            entries[0].published.isoformat()
            if entries
            else datetime.now(tz=timezone.utc).isoformat()
        )
        ET.SubElement(feed, _a("updated")).text = updated
        for e in entries:
            entry = ET.SubElement(feed, _a("entry"))
            ET.SubElement(entry, _a("title")).text = e.title
            ET.SubElement(entry, _a("id")).text = f"urn:mediainfo:{e.guid}"
            ET.SubElement(entry, _a("updated")).text = e.published.isoformat()
            if e.description:
                ET.SubElement(entry, _a("summary")).text = e.description
            if e.image_url:
                ET.SubElement(
                    entry,
                    _a("link"),
                    rel="enclosure",
                    href=e.image_url,
                    type=_image_mime(e.image_url),
                )
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(feed, encoding="unicode")
