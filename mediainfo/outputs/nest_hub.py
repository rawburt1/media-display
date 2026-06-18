"""Google Nest Hub output: casts the current artwork to a Google Cast
display (Nest Hub, Nest Hub Max, or any other Chromecast-compatible
display) using the Google Cast protocol.

Cast devices load media via an HTTP URL rather than accepting a direct
push, so this output runs a small built-in HTTP server that serves the
current image, and points the device's default media receiver at it.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

import pychromecast
from flask import Flask, send_file

from mediainfo.config import NestHubConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output
from mediainfo.transforms import parse_pipeline

logger = logging.getLogger(__name__)

_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
_DEFAULT_CONTENT_TYPE = "image/jpeg"

_RECONNECT_INTERVAL_SECONDS = 30
_CONNECT_TIMEOUT_SECONDS = 10


class NestHubOutput(Output):
    def __init__(self, config: NestHubConfig):
        self.config = config
        self.transform_pipeline = parse_pipeline(config.transforms)
        self._lock = threading.Lock()
        self._image_path: Optional[Path] = None
        self._cast = None
        self._last_url: Optional[str] = None
        self._last_connect_attempt: Optional[float] = None
        self._idle = False
        self.app = self._build_app()
        threading.Thread(target=self._run_server, daemon=True).start()

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        with self._lock:
            self._image_path = image_path

        self._idle = False
        self._cast_image(image_path)

    def on_idle(self) -> None:
        if self._idle:
            return

        cast = self._get_cast()
        if cast is None:
            return

        try:
            cast.quit_app()
            self._idle = True
            self._last_url = None
        except Exception:
            logger.exception("Failed to stop casting to Nest Hub")

    def _run_server(self) -> None:
        self.app.run(host="0.0.0.0", port=self.config.server_port)

    def _build_app(self) -> Flask:
        app = Flask(__name__)

        @app.get("/image/current")
        def current_image():
            with self._lock:
                image_path = self._image_path

            if image_path is None or not image_path.exists():
                return "", 404

            return send_file(image_path)

        return app

    def _cast_image(self, image_path: Path) -> None:
        content_type = _CONTENT_TYPES.get(image_path.suffix.lower(), _DEFAULT_CONTENT_TYPE)
        url = (
            f"http://{self.config.server_host}:{self.config.server_port}"
            f"/image/current?v={image_path.stem}"
        )
        if url == self._last_url:
            return

        cast = self._get_cast()
        if cast is None:
            return

        try:
            cast.media_controller.play_media(url, content_type)
            self._last_url = url
        except Exception:
            logger.exception("Failed to cast artwork to Nest Hub")
            self._cast = None

    def _get_cast(self):
        if self._cast is not None:
            return self._cast

        now = time.monotonic()
        if (
            self._last_connect_attempt is not None
            and now - self._last_connect_attempt < _RECONNECT_INTERVAL_SECONDS
        ):
            return None

        self._last_connect_attempt = now
        try:
            cast = pychromecast.get_chromecast_from_host(
                (self.config.device_ip, 8009, None, None, "Nest Hub")
            )
            cast.wait(timeout=_CONNECT_TIMEOUT_SECONDS)
        except Exception:
            logger.exception("Failed to connect to Nest Hub at %s", self.config.device_ip)
            return None

        self._cast = cast
        return cast
