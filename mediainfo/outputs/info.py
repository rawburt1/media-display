"""Info output: a high-resolution display pairing artwork with a bio/plot
summary (artist bio, movie info, TV show info - see the Wikipedia enricher).

Architecturally a sibling of the `web` output (same WebSocket-push design),
but laid out for a larger screen: image on one side, title/subtitle/summary
text on the other. No image transforms are applied by default, so artwork is
shown at its original resolution rather than scaled down for a small panel.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from flask import Flask, jsonify, send_file
from flask_sock import Sock

from mediainfo.cache import ImageCache
from mediainfo.config import InfoConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output
from mediainfo.transforms import parse_pipeline

logger = logging.getLogger(__name__)

_INDEX_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Now Playing - Info</title>
  <style>
    html, body { margin: 0; height: 100%; background: #000; color: #fff;
                  font-family: sans-serif; overflow: hidden; }
    #layout { display: flex; width: 100vw; height: 100vh; }
    #art-container { position: relative; flex: 1 1 60%; height: 100%; background: #000; }
    #art-container.fullscreen { flex: 1 1 100%; }
    #art-container img {
      position: absolute; top: 0; left: 0; width: 100%; height: 100%;
      object-fit: contain; opacity: 0; transition: opacity 1s ease-in-out;
    }
    #art-container.fullscreen img { object-fit: cover; }
    #art-container img.visible { opacity: 1; }
    #panel { flex: 0 0 40%; padding: 2em; box-sizing: border-box;
             display: flex; flex-direction: column; overflow-y: auto; }
    #panel.hidden { display: none; }
    #title { font-size: 2em; font-weight: 600; }
    #subtitle { font-size: 1.3em; opacity: 0.8; margin-top: 0.2em; }
    #summary { font-size: 1.1em; line-height: 1.5; margin-top: 1em; opacity: 0.95; }
  </style>
</head>
<body>
  <div id="layout">
    <div id="art-container">
      <img id="art-a" alt="">
      <img id="art-b" alt="">
    </div>
    <div id="panel">
      <div id="title"></div>
      <div id="subtitle"></div>
      <div id="summary"></div>
    </div>
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

    function applyState(data) {
      const title = document.getElementById("title");
      const subtitle = document.getElementById("subtitle");
      const summary = document.getElementById("summary");
      const artContainer = document.getElementById("art-container");
      const panel = document.getElementById("panel");

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

      const isIdle = data.source === "idle";
      artContainer.classList.toggle("fullscreen", isIdle);
      panel.classList.toggle("hidden", isIdle);

      title.textContent = data.title || "";
      subtitle.textContent = data.subtitle || "";
      summary.textContent = data.summary || "";
    }

    function connect() {
      const ws = new WebSocket("ws://" + location.host + "/ws");
      ws.onmessage = (event) => { applyState(JSON.parse(event.data)); };
      ws.onclose = () => { setTimeout(connect, 3000); };
      ws.onerror = () => { ws.close(); };
    }

    connect();
  </script>
</body>
</html>
"""


class InfoOutput(Output):
    def __init__(self, config: InfoConfig):
        self.config = config
        self.transform_pipeline = parse_pipeline(config.transforms)
        self._lock = threading.Lock()
        self._now_playing: Optional[NowPlaying] = None
        self._artwork: Optional[Artwork] = None
        self._image_path: Optional[Path] = None
        self._clients: set[Any] = set()
        self._clients_lock = threading.Lock()
        self.app = self._build_app()
        threading.Thread(target=self._run_server, daemon=True).start()

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
            "art_label": artwork.label if artwork else "",
        }
        if image_path is not None:
            payload["image"] = f"/image/current?v={image_path.stem}"
        return payload

    def _push(self, payload: dict) -> None:
        data = json.dumps(payload)
        with self._clients_lock:
            clients = list(self._clients)
        dead: set[Any] = set()
        for conn in clients:
            try:
                conn.send(data)
            except Exception:
                dead.add(conn)
        if dead:
            with self._clients_lock:
                self._clients -= dead

    def _run_server(self) -> None:
        logger.info("Starting info server on %s:%s", self.config.host, self.config.port)
        self.app.run(host=self.config.host, port=self.config.port, threaded=True)

    def _build_app(self) -> Flask:
        app = Flask(__name__)
        sock = Sock(app)

        @sock.route("/ws")
        def websocket(conn):
            with self._clients_lock:
                self._clients.add(conn)
            try:
                conn.send(json.dumps(self._get_payload()))
                while True:
                    conn.receive()
            except Exception:
                pass
            finally:
                with self._clients_lock:
                    self._clients.discard(conn)

        @app.get("/")
        def index():
            return _INDEX_HTML

        @app.get("/api/now-playing")
        def now_playing_json():
            return jsonify(self._get_payload())

        @app.get("/image/current")
        def current_image():
            with self._lock:
                image_path = self._image_path

            if image_path is None or not image_path.exists():
                return "", 404

            return send_file(image_path)

        return app
