"""Video output: serves a full-screen video player when idle, artwork when playing."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, send_file

from mediainfo.cache import ImageCache
from mediainfo.config import AuthConfig, VideoOutputConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output
from mediainfo.video.base import VideoClip, VideoSource
from mediainfo.web_auth import install_auth

logger = logging.getLogger(__name__)

_INDEX_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Video Display</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html, body { width: 100%; height: 100%; overflow: hidden; background: #000;
                  color: #fff; font-family: sans-serif; }
    .hidden { display: none !important; }

    #video-container {
      position: fixed; inset: 0; background: #000;
      display: flex; align-items: center; justify-content: center;
    }
    #player { width: 100%; height: 100%; object-fit: cover; }

    #art-container {
      position: fixed; inset: 0;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
    }
    #art-wrap { position: relative; width: 100vw; height: 85vh; }
    #art-wrap img {
      position: absolute; inset: 0; width: 100%; height: 100%;
      object-fit: contain; opacity: 0; transition: opacity 1s ease-in-out;
    }
    #art-wrap img.visible { opacity: 1; }
    #meta { padding: 0.5em; text-align: center; }
    #title { font-size: 1.5em; }
    #subtitle { font-size: 1em; opacity: 0.8; }
  </style>
</head>
<body>
  <div id="video-container" class="hidden">
    <video id="player" autoplay muted playsinline></video>
  </div>
  <div id="art-container" class="hidden">
    <div id="art-wrap">
      <img id="art-a" alt="">
      <img id="art-b" alt="">
    </div>
    <div id="meta">
      <div id="title"></div>
      <div id="subtitle"></div>
    </div>
  </div>

  <script>
    const player = document.getElementById('player');
    const videoContainer = document.getElementById('video-container');
    const artContainer = document.getElementById('art-container');
    let activeImg = document.getElementById('art-a');
    let standbyImg = document.getElementById('art-b');

    // --- Video playlist ---
    let playlist = [];
    let videoIndex = 0;
    let loadingVideos = false;

    function shuffled(arr) {
      const a = arr.slice();
      for (let i = a.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [a[i], a[j]] = [a[j], a[i]];
      }
      return a;
    }

    function playNext() {
      if (!playlist.length) return;
      player.src = playlist[videoIndex % playlist.length];
      videoIndex = (videoIndex + 1) % playlist.length;
      player.play().catch(() => {});
    }

    player.addEventListener('ended', playNext);
    player.addEventListener('error', () => setTimeout(playNext, 2000));

    async function loadVideos() {
      if (loadingVideos) return;
      loadingVideos = true;
      try {
        const res = await fetch('/api/videos');
        const vids = await res.json();
        if (vids.length) {
          playlist = shuffled(vids.map(v => v.url));
          videoIndex = 0;
          if (!player.src || player.paused) playNext();
        }
      } catch (e) {
        // network error; will retry on next poll
      } finally {
        loadingVideos = false;
      }
    }

    // --- Now-playing crossfade ---
    let lastImage = null;

    function showImage(src) {
      standbyImg.onload = standbyImg.onerror = () => {
        activeImg.classList.remove('visible');
        standbyImg.classList.add('visible');
        [activeImg, standbyImg] = [standbyImg, activeImg];
      };
      standbyImg.src = src;
    }

    // --- State polling ---
    let currentState = null;

    async function poll() {
      try {
        const res = await fetch('/api/state');
        const data = await res.json();

        if (data.state === 'idle') {
          if (currentState !== 'idle') {
            videoContainer.classList.remove('hidden');
            artContainer.classList.add('hidden');
            currentState = 'idle';
            if (playlist.length && player.paused) {
              player.play().catch(() => {});
            }
          }
          if (!playlist.length) loadVideos();

        } else {
          if (currentState !== 'playing') {
            artContainer.classList.remove('hidden');
            videoContainer.classList.add('hidden');
            if (player.src) player.pause();
          }
          currentState = 'playing';

          document.getElementById('title').textContent = data.title || '';
          document.getElementById('subtitle').textContent = data.subtitle || '';

          if (data.image && data.image !== lastImage) {
            artContainer.classList.remove('hidden');
            showImage(data.image);
            lastImage = data.image;
          } else if (!data.image) {
            activeImg.classList.remove('visible');
            standbyImg.classList.remove('visible');
            lastImage = null;
          }
        }
      } catch (e) {
        // Ignore transient errors.
      } finally {
        setTimeout(poll, 5000);
      }
    }

    poll();
  </script>
</body>
</html>
"""


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

    def __init__(self, config: VideoOutputConfig, auth_config: Optional[AuthConfig] = None):
        self.config = config
        self.auth_config = auth_config
        self._lock = threading.Lock()
        self._now_playing: Optional[NowPlaying] = None
        self._artwork: Optional[Artwork] = None
        self._image_path: Optional[Path] = None
        self._is_idle: bool = True
        self._videos: list[VideoClip] = []
        self._last_refresh: float = 0.0
        self._refresh_thread: Optional[threading.Thread] = None
        self._video_source = _make_video_source(config)
        self.app = self._build_app()
        threading.Thread(target=self._run_server, daemon=True).start()

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

    # --- Flask server ---

    def _run_server(self) -> None:
        logger.info("Starting video server on %s:%s", self.config.host, self.config.port)
        self.app.run(host=self.config.host, port=self.config.port)

    def _build_app(self) -> Flask:
        app = Flask(__name__)

        @app.get("/")
        def index():
            return _INDEX_HTML

        @app.get("/api/state")
        def state():
            with self._lock:
                is_idle = self._is_idle
                now_playing = self._now_playing
                artwork = self._artwork
                image_path = self._image_path

            if is_idle:
                return jsonify({"state": "idle"})

            payload: dict = {
                "state": "playing",
                "title": now_playing.title if now_playing else "",
                "subtitle": now_playing.subtitle if now_playing else "",
            }
            if image_path is not None:
                payload["image"] = f"/image/current?v={image_path.stem}"
            return jsonify(payload)

        @app.get("/api/videos")
        def videos():
            with self._lock:
                clips = list(self._videos)
            return jsonify([{"url": c.url, "label": c.label} for c in clips])

        @app.get("/image/current")
        def current_image():
            with self._lock:
                image_path = self._image_path

            if image_path is None or not image_path.exists():
                return "", 404

            return send_file(image_path)

        install_auth(app, self.auth_config)
        return app
