"""Google Nest Hub output: casts the current artwork to a Google Cast
display (Nest Hub, Nest Hub Max, or any other Chromecast-compatible
display) using the Google Cast protocol.

Cast devices load media via an HTTP URL rather than accepting a direct
push, so this output runs a small built-in HTTP server that serves the
current image, and points the device's default media receiver at it.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import pychromecast
from flask import Blueprint, send_file

from mediainfo.config import NestHubConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output
from mediainfo.imaging.transforms import parse_pipeline

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
    name = "nest_hub"
    config_class = NestHubConfig

    def __init__(self, config: NestHubConfig, http_port: int = 8090):
        self.config = config
        # The shared HTTP server's port (see mediainfo/outputs/http_server.py)
        # - needed here (unlike every other Flask-based output) because
        # _cast_image() builds an absolute URL for a physical Cast device to
        # fetch, rather than a browser resolving a relative one.
        self.http_port = http_port
        self.transform_pipeline = parse_pipeline(config.transforms)
        self._lock = threading.Lock()
        # Stable file that survives idle rotations so the Nest Hub can always
        # fetch the image, even after the original temp file has been deleted.
        self._stable_path: Optional[Path] = None
        self._stable_content_type: str = _DEFAULT_CONTENT_TYPE
        self._cast = None
        self._last_url: Optional[str] = None
        self._last_connect_attempt: Optional[float] = None
        self._idle = False
        # Set by build_http_blueprint() once wiring.py has computed it.
        self._url_prefix = ""

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        content_type = _CONTENT_TYPES.get(image_path.suffix.lower(), _DEFAULT_CONTENT_TYPE)

        # Copy to a stable temp file we manage ourselves.  The caller
        # (orchestrator_idle) deletes the original image_path immediately
        # after update() returns, so we must have our own persistent copy
        # before _cast_image() tells the Nest Hub to fetch it.
        suffix = image_path.suffix or ".jpg"
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        try:
            stable = Path(tmp)
            shutil.copy2(image_path, stable)
        finally:
            os.close(fd)

        with self._lock:
            old = self._stable_path
            self._stable_path = stable
            self._stable_content_type = content_type

        # Delete the previous stable file now that we have a new one.
        if old is not None:
            try:
                old.unlink(missing_ok=True)
            except OSError:
                pass

        logger.debug("NestHub image updated: %s (%d bytes)", stable.name, stable.stat().st_size)
        self._idle = False
        self._cast_image(image_path)

    def on_idle(self) -> None:
        if self._idle:
            return

        cast = self._get_cast()
        if cast is None:
            # Deliberately raises rather than silently no-op'ing - lets the
            # orchestrator's _call_output() record it for health/alerting
            # (see orchestrator.py:_call_output). _get_cast() already
            # throttles/logs its own reconnect attempts, so this doesn't
            # spam a fresh connection attempt on every tick.
            raise ConnectionError(f"Nest Hub at {self.config.device_ip} is unreachable")

        try:
            cast.quit_app()
        except Exception:
            self._drop_cast()
            raise
        self._idle = True
        self._last_url = None

    def build_http_blueprint(self, url_prefix: str, sock=None) -> Blueprint:
        self._url_prefix = url_prefix
        bp = Blueprint("nest_hub", __name__)

        @bp.get("/image/current")
        def current_image():
            with self._lock:
                path = self._stable_path
                content_type = self._stable_content_type
            if path is None or not path.exists():
                logger.debug("NestHub /image/current: no image available (path=%s)", path)
                return "", 404
            return send_file(path, mimetype=content_type)

        return bp

    def _cast_image(self, image_path: Path) -> None:
        content_type = _CONTENT_TYPES.get(image_path.suffix.lower(), _DEFAULT_CONTENT_TYPE)
        url = (
            f"http://{self.config.server_host}:{self.http_port}"
            f"{self._url_prefix}/image/current?v={image_path.stem}"
        )
        if url == self._last_url:
            return

        cast = self._get_cast()
        if cast is None:
            # Deliberately raises rather than silently no-op'ing - lets the
            # orchestrator's _call_output() record it for health/alerting
            # (see orchestrator.py:_call_output). _get_cast() already
            # throttles/logs its own reconnect attempts, so this doesn't
            # spam a fresh connection attempt on every tick.
            raise ConnectionError(f"Nest Hub at {self.config.device_ip} is unreachable")

        try:
            cast.media_controller.play_media(url, content_type)
        except Exception:
            self._drop_cast()
            raise
        self._last_url = url

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
        cast = None
        try:
            cast = pychromecast.get_chromecast_from_host(
                (self.config.device_ip, 8009, None, None, "Nest Hub")
            )
            cast.wait(timeout=_CONNECT_TIMEOUT_SECONDS)
        except Exception:
            logger.exception("Failed to connect to Nest Hub at %s", self.config.device_ip)
            # get_chromecast_from_host() already spun up the Chromecast's
            # background SocketClient thread even though .wait() then
            # failed - dropping `cast` here without disconnecting leaves
            # that thread retrying forever, each attempt leaking a socket
            # (pychromecast.socket_client.SocketClient owns a
            # socket.socketpair() used to interrupt its own thread, never
            # closed unless disconnect() runs).
            if cast is not None:
                self._close_cast(cast)
            return None

        self._cast = cast
        return cast

    def _drop_cast(self) -> None:
        """Disconnect the current cast connection and clear it - same
        leaked-thread rationale as the comment in _get_cast(), but for a
        previously-working connection that just failed a call.
        """
        cast = self._cast
        self._cast = None
        if cast is not None:
            self._close_cast(cast)

    @staticmethod
    def _close_cast(cast) -> None:
        try:
            cast.disconnect(timeout=_CONNECT_TIMEOUT_SECONDS, blocking=False)
        except Exception:
            logger.debug("Nest Hub: error disconnecting stale cast connection", exc_info=True)
