"""Web output: serves the current artwork and metadata over HTTP."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, send_file

from pixoo_media.config import WebConfig
from pixoo_media.models import Artwork, NowPlaying
from pixoo_media.outputs.base import Output

logger = logging.getLogger(__name__)

_INDEX_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Now Playing</title>
  <style>
    html, body { margin: 0; height: 100%; background: #000; color: #fff;
                  font-family: sans-serif; display: flex; flex-direction: column;
                  align-items: center; justify-content: center; }
    #art-container { position: relative; width: 100vw; height: 90vh; }
    #art-container img {
      position: absolute; top: 0; left: 0; width: 100%; height: 100%;
      object-fit: contain; opacity: 0; transition: opacity 1s ease-in-out;
    }
    #art-container img.visible { opacity: 1; }
    #meta { text-align: center; padding: 0.5em; }
    #title { font-size: 1.5em; }
    #subtitle { font-size: 1em; opacity: 0.8; }
    #art-label { font-size: 0.8em; opacity: 0.5; margin-top: 0.3em; }
  </style>
</head>
<body>
  <div id="art-container">
    <img id="art-a" alt="">
    <img id="art-b" alt="">
  </div>
  <div id="meta">
    <div id="title"></div>
    <div id="subtitle"></div>
    <div id="art-label"></div>
  </div>
  <script>
    let lastImage = null;
    let activeImg = document.getElementById("art-a");
    let standbyImg = document.getElementById("art-b");

    function showImage(src) {
      standbyImg.onload = standbyImg.onerror = () => {
        activeImg.classList.remove("visible");
        standbyImg.classList.add("visible");
        [activeImg, standbyImg] = [standbyImg, activeImg];
      };
      standbyImg.src = src;
    }

    async function poll() {
      try {
        const res = await fetch("/api/now-playing");
        const data = await res.json();
        const title = document.getElementById("title");
        const subtitle = document.getElementById("subtitle");
        const artLabel = document.getElementById("art-label");

        if (data.image) {
          if (data.image !== lastImage) {
            showImage(data.image);
            lastImage = data.image;
          }
        } else {
          activeImg.classList.remove("visible");
          standbyImg.classList.remove("visible");
          lastImage = null;
        }
        title.textContent = data.title || "";
        subtitle.textContent = data.subtitle || "";
        artLabel.textContent = data.art_label || "";
      } catch (err) {
        // Ignore transient errors; try again on the next poll.
      } finally {
        setTimeout(poll, 5000);
      }
    }

    poll();
  </script>
</body>
</html>
"""


class WebOutput(Output):
    def __init__(self, config: WebConfig):
        self.config = config
        self._lock = threading.Lock()
        self._now_playing: Optional[NowPlaying] = None
        self._artwork: Optional[Artwork] = None
        self._image_path: Optional[Path] = None
        self.app = self._build_app()

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        with self._lock:
            self._now_playing = now_playing
            self._artwork = artwork
            self._image_path = image_path

    def on_idle(self) -> None:
        with self._lock:
            self._now_playing = None
            self._artwork = None
            self._image_path = None

    def run(self) -> None:
        self.app.run(host=self.config.host, port=self.config.port)

    def _build_app(self) -> Flask:
        app = Flask(__name__)

        @app.get("/")
        def index():
            return _INDEX_HTML

        @app.get("/api/now-playing")
        def now_playing_json():
            with self._lock:
                now_playing = self._now_playing
                artwork = self._artwork
                image_path = self._image_path

            if now_playing is None or image_path is None:
                return jsonify({})

            return jsonify(
                {
                    "source": now_playing.source,
                    "media_type": now_playing.media_type,
                    "title": now_playing.title,
                    "subtitle": now_playing.subtitle,
                    "art_label": artwork.label if artwork else "",
                    "image": f"/image/current?v={image_path.stem}",
                }
            )

        @app.get("/image/current")
        def current_image():
            with self._lock:
                image_path = self._image_path

            if image_path is None or not image_path.exists():
                return "", 404

            return send_file(image_path)

        return app
