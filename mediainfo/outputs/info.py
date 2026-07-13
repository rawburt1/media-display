"""Info output: a high-resolution display pairing artwork with a bio/plot
summary (artist bio, movie info, TV show info - see the Wikipedia enricher).

Architecturally a sibling of the `web` output (same WebSocket-push design),
but laid out for a larger screen: image on one side, title/subtitle/summary
text on the other. No image transforms are applied by default, so artwork is
shown at its original resolution rather than scaled down for a small panel.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Optional

from flask import Blueprint, jsonify, render_template, send_file
from flask_sock import Sock
from markupsafe import Markup

from mediainfo.cache import ImageCache
from mediainfo.config import InfoConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs import transitions
from mediainfo.outputs.base import Output
from mediainfo.outputs.websocket_push import (
    add_playback_position,
    broadcast,
    register_websocket_route,
)
from mediainfo.imaging.transforms import parse_pipeline

logger = logging.getLogger(__name__)


class InfoOutput(Output):
    name = "info"
    config_class = InfoConfig

    def __init__(self, config: InfoConfig):
        self.config = config
        self.transform_pipeline = parse_pipeline(config.transforms)
        # Markup: the transitions CSS/JS is code, not text - autoescaping it
        # would corrupt it (see templates/info/index.html).
        self._transitions_css = Markup(transitions.transitions_css())
        self._transitions_js = Markup(transitions.transitions_js(config.transition_exclude))
        self._lock = threading.Lock()
        self._now_playing: Optional[NowPlaying] = None
        self._artwork: Optional[Artwork] = None
        self._image_path: Optional[Path] = None
        self._clients: set[Any] = set()
        self._clients_lock = threading.Lock()
        # Set by build_http_blueprint() once wiring.py has computed it -
        # baked into the /image/current URL handed to clients, since it's a
        # relative path a browser resolves against the current page.
        self._url_prefix = ""

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        with self._lock:
            self._now_playing = now_playing
            self._artwork = artwork
            self._image_path = image_path
        self._push(self._get_payload())

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        # Push title/subtitle/summary immediately; the image URL follows in update().
        with self._lock:
            self._now_playing = now_playing
            self._artwork = None
            self._image_path = None
        self._push(self._get_payload())

    def on_idle(self) -> None:
        with self._lock:
            self._now_playing = None
            self._artwork = None
            self._image_path = None
        self._push({})

    def _get_payload(self) -> dict:
        with self._lock:
            now_playing = self._now_playing
            artwork = self._artwork
            image_path = self._image_path

        if now_playing is None:
            return {}

        payload: dict = {
            "source": now_playing.source,
            "media_type": now_playing.media_type,
            "title": now_playing.title,
            "subtitle": now_playing.subtitle,
            "summary": now_playing.summary,
            "rating": now_playing.rating,
            "art_label": artwork.label if artwork else "",
        }
        add_playback_position(payload, now_playing)
        if image_path is not None:
            payload["image"] = f"{self._url_prefix}/image/current?v={image_path.stem}"
        return payload

    def _push(self, payload: dict) -> None:
        broadcast(self._clients_lock, self._clients, payload)

    def build_http_blueprint(self, url_prefix: str, sock: Optional[Sock] = None) -> Blueprint:
        self._url_prefix = url_prefix
        bp = Blueprint("info", __name__)

        if sock is not None:
            register_websocket_route(
                sock,
                "/ws",
                self._clients_lock,
                self._clients,
                get_initial_payload=lambda conn: self._get_payload(),
                bp=bp,
            )

        @bp.get("/")
        def index():
            return render_template(
                "info/index.html",
                transitions_css=self._transitions_css,
                transitions_js=self._transitions_js,
                url_prefix=url_prefix,
            )

        @bp.get("/api/now-playing")
        def now_playing_json():
            return jsonify(self._get_payload())

        @bp.get("/image/current")
        def current_image():
            with self._lock:
                image_path = self._image_path

            if image_path is None or not image_path.exists():
                return "", 404

            return send_file(image_path)

        return bp
