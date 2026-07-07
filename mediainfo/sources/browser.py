"""Browser extension "now playing" source.

Unlike every other source, this one doesn't poll anything - it runs a
small WebSocket server (Flask + flask_sock, the same libraries the web/
info outputs already use) that the companion browser extension
(browser-extension/) connects to and pushes normalized now-playing events
into, one per active/changed tab. get_now_playing() just reads whatever
was most recently received, kept in memory - there is no outbound network
call in this source at all.

Mirrors AppleTvSource in starting its own background work directly in
__init__ (a thread running the Flask app) rather than via some separate
lifecycle hook - MediaSource has no start() method, so every source that
needs a background thread just starts it in its own constructor.

The extension is expected to already have normalized `media_type` to this
project's vocabulary ("music" | "movie" | "episode") per site, rather than
this source guessing it from whatever a site's own metadata calls itself -
see browser-extension/shared/media-state.js.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

from flask import Flask, request
from flask_sock import Sock

from mediainfo.config import BrowserConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# Mirrors every other source: only "playing" entries are ever surfaced -
# paused/stopped tabs are treated the same as no tab at all (idle).
_ACTIVE_STATES = {"playing"}


class BrowserSource(MediaSource):
    name = "browser"

    def __init__(self, config: BrowserConfig):
        self.config = config
        self._lock = threading.Lock()
        # key (the event's "url", falling back to "site") -> (event dict,
        # time.monotonic() it was received at). One entry per distinct
        # tab/stream, so multiple open tabs don't clobber each other -
        # each fresh event for the same key just replaces its own entry.
        self._entries: dict = {}
        self.app = self._build_app()
        threading.Thread(target=self._run_server, daemon=True).start()

    def _run_server(self) -> None:
        self.app.run(host=self.config.host, port=self.config.port, threaded=True)

    def _build_app(self) -> Flask:
        app = Flask(__name__)
        sock = Sock(app)

        @sock.route("/ws")
        def _handler(conn):
            if not self._is_authorized(request.args):
                logger.warning("Browser source: rejected a connection with a missing/incorrect token")
                return
            try:
                while True:
                    raw = conn.receive()
                    if raw is None:
                        break
                    self._handle_message(raw)
            except Exception:
                logger.exception("Browser source: error handling a WebSocket message")

        return app

    def _is_authorized(self, args) -> bool:
        """True if this connection may proceed: no token configured means
        "accept anything" (fine on a trusted local network), otherwise the
        connection's "token" query parameter must match exactly."""
        return not self.config.token or args.get("token") == self.config.token

    def _handle_message(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except ValueError:
            logger.warning("Browser source: ignoring a non-JSON message")
            return
        if not isinstance(event, dict):
            logger.warning("Browser source: ignoring a message that isn't a JSON object")
            return

        key = event.get("url") or event.get("site")
        if not key:
            logger.warning("Browser source: ignoring an event with neither 'url' nor 'site'")
            return

        with self._lock:
            self._entries[key] = (event, time.monotonic())

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
        cutoff = time.monotonic() - self.config.timeout

        with self._lock:
            # Drop stale entries here too, so a browser that's gone quiet
            # doesn't leave this dict growing forever.
            self._entries = {k: v for k, v in self._entries.items() if v[1] >= cutoff}
            fresh = list(self._entries.values())

        playing = [(event, ts) for event, ts in fresh if event.get("state") in _ACTIVE_STATES]
        if not playing:
            return None

        # The most recently updated actively-playing tab wins - a
        # reasonable proxy for "most relevant" without needing the
        # extension to track OS-level tab focus.
        event, _ = max(playing, key=lambda pair: pair[1])
        return self._to_now_playing(event)

    @staticmethod
    def _to_now_playing(event: dict) -> NowPlaying:
        images = []
        artwork_url = event.get("artwork_url")
        if artwork_url:
            images.append(Artwork(url=artwork_url, label=f"Artwork ({event.get('site', 'browser')})"))

        artist = event.get("artist") or ""
        duration = event.get("duration")
        progress = event.get("progress")
        site = event.get("site")

        return NowPlaying(
            source="browser",
            media_type=event.get("media_type") or "movie",
            title=event.get("title") or "",
            subtitle=artist,
            album=event.get("album") or "",
            artist=artist,
            device=f"Browser ({site})" if site else "Browser",
            images=images,
            position_seconds=float(progress) if progress is not None else None,
            duration_seconds=float(duration) if duration is not None else None,
        )
