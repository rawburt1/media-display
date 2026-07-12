"""Video output: serves a full-screen video player when idle, artwork when playing."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from flask import Blueprint, jsonify, render_template, send_file
from markupsafe import Markup

from mediainfo.cache import ImageCache
from mediainfo.config import VideoOutputConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs import transitions
from mediainfo.outputs.base import Output
from mediainfo.video.base import VideoClip, VideoSource

logger = logging.getLogger(__name__)


def _make_video_source(config: VideoOutputConfig) -> VideoSource:
    if config.source == "pixabay":
        from mediainfo.video.pixabay import PixabayVideoSource

        return PixabayVideoSource(
            api_key=config.pixabay_api_key,
            queries=config.queries,
            batch_size=config.batch_size,
        )
    from mediainfo.video.pexels import PexelsVideoSource

    return PexelsVideoSource(
        api_key=config.pexels_api_key,
        queries=config.queries,
        batch_size=config.batch_size,
    )


class VideoOutput(Output):
    # Manages its own idle video content; idle Unsplash wallpapers are not
    # routed here (see _show_idle_image_for_output in orchestrator).
    handles_images = False

    def __init__(self, config: VideoOutputConfig):
        self.config = config
        # Markup: the transitions CSS/JS is code, not text - autoescaping it
        # would corrupt it (see templates/video/index.html).
        self._transitions_css = Markup(transitions.transitions_css("#art-wrap"))
        self._transitions_js = Markup(transitions.transitions_js(config.transition_exclude))
        self._lock = threading.Lock()
        self._now_playing: Optional[NowPlaying] = None
        self._artwork: Optional[Artwork] = None
        self._image_path: Optional[Path] = None
        self._is_idle: bool = True
        self._videos: list[VideoClip] = []
        self._last_refresh: float = 0.0
        self._refresh_thread: Optional[threading.Thread] = None
        self._video_source = _make_video_source(config)
        # Set by build_http_blueprint() once wiring.py has computed it -
        # baked into /api/state's "image" URL, since it's a relative path
        # a browser resolves against the current page.
        self._url_prefix = ""

    # --- Output interface ---

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        with self._lock:
            self._now_playing = now_playing
            self._artwork = artwork
            self._image_path = image_path
            self._is_idle = False

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        with self._lock:
            self._now_playing = now_playing
            self._artwork = None
            self._image_path = None
            # Show videos when no artwork is expected; switch to playing mode
            # (title/subtitle visible) when artwork is incoming via update().
            self._is_idle = not bool(now_playing.images)

    def on_idle(self) -> None:
        with self._lock:
            self._now_playing = None
            self._artwork = None
            self._image_path = None
            self._is_idle = True
        self._maybe_refresh_videos()

    def idle_health_entry(self) -> dict:
        """Return a health dict entry for this output's idle video source."""
        with self._lock:
            n = len(self._videos)
        return {
            "type": self.config.source,
            "status": "ok" if n > 0 else "idle",
            "videos_loaded": n,
        }

    # --- Video refresh ---

    def _maybe_refresh_videos(self) -> None:
        now = time.monotonic()
        with self._lock:
            if self._videos and now - self._last_refresh < self.config.refresh_interval_seconds:
                return
            if self._refresh_thread and self._refresh_thread.is_alive():
                return
            self._refresh_thread = threading.Thread(target=self._refresh_videos, daemon=True)
        self._refresh_thread.start()

    def _refresh_videos(self) -> None:
        videos = self._video_source.get_videos()
        if videos:
            with self._lock:
                self._videos = videos
                self._last_refresh = time.monotonic()

    # --- Flask blueprint ---

    def build_http_blueprint(self, url_prefix: str, sock=None) -> Blueprint:
        self._url_prefix = url_prefix
        bp = Blueprint("video", __name__)

        @bp.get("/")
        def index():
            return render_template(
                "video/index.html",
                transitions_css=self._transitions_css,
                transitions_js=self._transitions_js,
            )

        @bp.get("/api/state")
        def state():
            with self._lock:
                is_idle = self._is_idle
                now_playing = self._now_playing
                image_path = self._image_path

            if is_idle:
                return jsonify({"state": "idle"})

            payload: dict = {
                "state": "playing",
                "title": now_playing.title if now_playing else "",
                "subtitle": now_playing.subtitle if now_playing else "",
            }
            if image_path is not None:
                payload["image"] = f"{self._url_prefix}/image/current?v={image_path.stem}"
            return jsonify(payload)

        @bp.get("/api/videos")
        def videos():
            with self._lock:
                clips = list(self._videos)
            return jsonify([{"url": c.url, "label": c.label} for c in clips])

        @bp.get("/image/current")
        def current_image():
            with self._lock:
                image_path = self._image_path

            if image_path is None or not image_path.exists():
                return "", 404

            return send_file(image_path)

        return bp
