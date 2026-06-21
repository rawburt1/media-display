"""Web output: serves the current artwork and metadata over HTTP/WebSocket.

The browser opens a persistent WebSocket connection on /ws. Multiple
browsers/screens can connect to the same port - rather than every one of
them seeing an identical broadcast (which is what every *other* output
gets: one device, one current image, chosen once by the orchestrator),
each WebSocket connection here gets its own independent rotation through
NowPlaying.images, on its own randomized order and its own staggered
timer - mirroring how Orchestrator._build_rotation_states() desynchronizes
multiple *outputs*, just one level down, across multiple *clients* of this
one output. Other outputs are one physical device each, so the
orchestrator's own per-output rotation is enough; this one is effectively
N logical displays sharing a single port, so it needs the same trick
applied to its own connections.

The orchestrator's own update()/on_new_item() calls still drive the
*shared* now-playing metadata and image pool (NowPlaying.images), and a
single "current pick" used by the /image/current and /api/now-playing
HTTP endpoints for diagnostics/non-browser clients - but which image each
WebSocket client is actually shown is decided here, independently.

The /image/current endpoint takes a `v=<stem>` query param identifying
which cached file to serve (looked up in `_known_images`, populated as
each client's image gets resolved) - falling back to the single most
recent "global pick" when `v` is absent/unrecognized, for the legacy
non-multi-client HTTP clients.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request, send_file
from flask_sock import Sock

from mediainfo.cache import ImageCache
from mediainfo.config import AuthConfig, WebConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs import transitions
from mediainfo.outputs.base import Output
from mediainfo.transforms import parse_pipeline
from mediainfo.web_auth import install_auth

logger = logging.getLogger(__name__)

# How often the background thread checks for clients due to rotate to
# their next image. Independent of (and much finer-grained than)
# rotation_interval_seconds, which controls how often any given client
# actually advances.
_ROTATION_CHECK_INTERVAL_SECONDS = 1.0


@dataclasses.dataclass
class _ClientRotation:
    """One WebSocket client's independent position in a randomized cycle
    through the current NowPlaying.images, shared with other clients only
    via the (read-only, never mutated after creation) `order` list."""

    order: List[int]
    position: int
    next_due: float

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
    #art-container.fullscreen { height: 100vh; }
    #art-container img {
      position: absolute; top: 0; left: 0; width: 100%; height: 100%;
      object-fit: contain; opacity: 0;
      transition: opacity 1s ease-in-out, transform 1s ease-in-out;
    }
    #art-container.fullscreen img { object-fit: cover; }
    /* __TRANSITIONS_CSS__ */
    #meta { text-align: center; padding: 0.5em; }
    #meta.hidden { display: none; }
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
    /* __TRANSITIONS_JS__ */

    let lastImage = null;
    let activeImg = document.getElementById("art-a");
    let standbyImg = document.getElementById("art-b");

    function showImage(src) {
      prepareForTransition(standbyImg);
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
      const artLabel = document.getElementById("art-label");
      const artContainer = document.getElementById("art-container");
      const meta = document.getElementById("meta");

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
      meta.classList.toggle("hidden", isIdle);

      title.textContent = data.title || "";
      subtitle.textContent = data.subtitle || "";
      artLabel.textContent = data.art_label || "";
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


_HEALTH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>mediainfo · health</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #080d1a; color: #c0ccdf;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 14px; min-height: 100vh;
      padding: 24px 20px; max-width: 1080px; margin: 0 auto;
    }
    h1 { font-size: 17px; font-weight: 700; color: #e8f0ff; }

    /* Header */
    .hdr { display: flex; align-items: center; gap: 12px;
           margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid #141e33; }
    .hdr-icon { width: 32px; height: 32px; border-radius: 9px; background: #10203f;
                display: flex; align-items: center; justify-content: center; font-size: 17px; }
    .uptime { font-size: 12px; color: #6b7fa8; background: #0d1629;
              padding: 4px 10px; border-radius: 6px; border: 1px solid #1a2540; }
    .pill { margin-left: auto; padding: 5px 14px; border-radius: 999px;
            font-size: 11px; font-weight: 700; letter-spacing: 0.9px; text-transform: uppercase; }
    .pill.healthy  { background: #051a0d; color: #22c55e; border: 1px solid #0d3320; }
    .pill.degraded { background: #1a0505; color: #f87171; border: 1px solid #33100d; }
    .pill.loading  { background: #0d1629; color: #6b7fa8; border: 1px solid #1a2540; }

    /* Now Playing */
    .np { background: #0d1629; border: 1px solid #1a2540; border-radius: 14px;
          padding: 16px 20px; margin-bottom: 18px; display: flex; align-items: center; gap: 14px; }
    .np-bar { width: 5px; height: 44px; border-radius: 3px; flex-shrink: 0; }
    .np-body { flex: 1; min-width: 0; }
    .sect-label { font-size: 10px; font-weight: 700; letter-spacing: 1.3px;
                  text-transform: uppercase; color: #3b5070; margin-bottom: 5px; }
    .np-title { font-size: 16px; font-weight: 600; color: #dce8ff;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .np-meta { font-size: 12px; color: #4a5f7a; margin-top: 3px; }
    .np-idle .np-title { color: #3b5070; font-style: italic; font-size: 14px; }
    .np-count { font-size: 11px; color: #3b5070; white-space: nowrap; }

    /* Grid */
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
    @media (max-width: 600px) { .grid2 { grid-template-columns: 1fr; } }

    /* Cards */
    .card { background: #0d1629; border: 1px solid #1a2540; border-radius: 14px; padding: 16px 18px; }

    /* Items */
    .item { display: grid; grid-template-columns: 12px 1fr auto auto;
            align-items: center; gap: 8px; padding: 7px 0;
            border-bottom: 1px solid #080d1a; }
    .item:last-child { border-bottom: none; }
    .dot { font-size: 7px; }
    .iname { font-size: 13px; font-weight: 500; color: #a0b4cc;
             white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .idetail { font-size: 11px; color: #4a5f7a; font-family: ui-monospace, monospace;
               text-align: right; white-space: nowrap; }
    .badge { font-size: 10px; font-weight: 700; letter-spacing: 0.3px;
             padding: 2px 7px; border-radius: 4px; white-space: nowrap; }
    .img-tag { display: inline-block; font-size: 11px; color: #6b7fa8;
               background: #111827; border: 1px solid #1a2540;
               border-radius: 4px; padding: 1px 7px; margin: 3px 3px 0 0; }
    .err-msg { grid-column: 2 / -1; font-size: 11px; color: #c87070;
               font-family: ui-monospace, monospace; background: #0d0505;
               border-radius: 4px; padding: 3px 7px; margin-top: -3px;
               white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

    /* Status colours — dot colour class / badge style */
    .c-ok  { color: #22c55e; } .bg-ok  { background: #031108; color: #22c55e; }
    .c-act { color: #4ade80; } .bg-act { background: #031108; color: #4ade80; }
    .c-idl { color: #60a5fa; } .bg-idl { background: #050f24; color: #60a5fa; }
    .c-dis { color: #f59e0b; } .bg-dis { background: #150e00; color: #f59e0b; }
    .c-ncf { color: #94a3b8; } .bg-ncf { background: #111827; color: #94a3b8; }
    .c-err { color: #f87171; } .bg-err { background: #130303; color: #f87171; }
    .c-wrn { color: #f59e0b; } .bg-wrn { background: #150e00; color: #f59e0b; }

    .footer { margin-top: 18px; font-size: 11px; color: #1e2d40; text-align: center; }
  </style>
</head>
<body>
<div class="hdr">
  <div class="hdr-icon">&#x1F4FA;</div>
  <h1>mediainfo</h1>
  <span class="uptime" id="uptime">&#x2014;</span>
  <span class="pill loading" id="pill">loading</span>
</div>

<div class="np" id="np">
  <div class="np-bar" id="np-bar" style="background:#1a2540"></div>
  <div class="np-body">
    <div class="sect-label">Now Playing</div>
    <div class="np-title" id="np-title">&#x2014;</div>
    <div class="np-meta"  id="np-meta"></div>
    <div id="np-imgs" style="margin-top:6px"></div>
  </div>
  <div class="np-count" id="np-count"></div>
</div>

<div class="grid2">
  <div class="card"><div class="sect-label">Sources</div><div id="sources"></div></div>
  <div class="card"><div class="sect-label">Outputs</div><div id="outputs"></div></div>
</div>
<div class="grid2">
  <div class="card"><div class="sect-label">Enrichers</div><div id="enrichers"></div></div>
  <div class="card"><div class="sect-label">Idle Sources</div><div id="idle"></div></div>
</div>

<div class="footer" id="footer">connecting&hellip;</div>

<script>
var P = {
  ok:             {dot:'c-ok',  bg:'bg-ok',  lbl:'ok'},
  active:         {dot:'c-act', bg:'bg-act', lbl:'active'},
  idle:           {dot:'c-idl', bg:'bg-idl', lbl:'idle'},
  disabled:       {dot:'c-dis', bg:'bg-dis', lbl:'disabled'},
  not_configured: {dot:'c-ncf', bg:'bg-ncf', lbl:'not configured'},
  error:          {dot:'c-err', bg:'bg-err', lbl:'error'},
  starting:       {dot:'c-wrn', bg:'bg-wrn', lbl:'starting'},
};

function p(s){ return P[s] || P.not_configured; }
function badge(s){ return '<span class="badge ' + p(s).bg + '">' + p(s).lbl + '</span>'; }
function dot(s)  { return '<span class="dot '   + p(s).dot + '">&#9679;</span>'; }

function fmtUp(s){
  s = Math.round(s);
  if (s < 60)   return s + 's';
  if (s < 3600) return Math.floor(s/60) + 'm ' + (s%60) + 's';
  return Math.floor(s/3600) + 'h ' + Math.floor((s%3600)/60) + 'm';
}
function fmtAgo(s){
  if (s == null) return '';
  s = Math.round(s);
  return s < 60 ? s + 's ago' : Math.floor(s/60) + 'm ago';
}

function row(name, status, detail, errMsg){
  var err = errMsg ? '<div class="err-msg">&#x26A0; ' + errMsg.slice(0,120) + '</div>' : '';
  return '<div class="item">'
    + dot(status)
    + '<span class="iname">' + name + '</span>'
    + '<span class="idetail">' + (detail||'') + '</span>'
    + badge(status) + err
    + '</div>';
}

function render(d){
  var hasErr = (d.outputs||[]).some(function(o){ return o.status === 'error'; });
  var overall = hasErr ? 'degraded' : 'healthy';
  var pill = document.getElementById('pill');
  pill.textContent = overall;
  pill.className = 'pill ' + overall;
  document.getElementById('uptime').textContent = 'up ' + fmtUp(d.uptime_seconds||0);

  var np = d.now_playing;
  var npEl = document.getElementById('np');
  var barColors = {music:'#7c3aed', movie:'#2563eb', episode:'#0891b2', wallpaper:'#1e3a5f'};
  if (np) {
    npEl.classList.remove('np-idle');
    document.getElementById('np-bar').style.background = barColors[np.media_type] || '#3b5070';
    var title = np.title || '&#x2014;';
    if (np.subtitle) title += ' \xb7 ' + np.subtitle;
    document.getElementById('np-title').textContent = title;
    var parts = [];
    if (np.media_type) parts.push(np.media_type);
    if (np.source)     parts.push('via ' + np.source);
    document.getElementById('np-meta').textContent = parts.join(' \xb7 ');
    var imgs = np.images || [];
    document.getElementById('np-count').textContent =
      imgs.length > 0 ? imgs.length + ' image' + (imgs.length > 1 ? 's' : '') : '';
    document.getElementById('np-imgs').innerHTML = imgs.map(function(lbl){
      return '<span class="img-tag">' + lbl + '</span>';
    }).join('');
  } else {
    npEl.classList.add('np-idle');
    document.getElementById('np-bar').style.background = '#1a2540';
    document.getElementById('np-title').textContent = 'Nothing playing';
    document.getElementById('np-meta').textContent = '';
    document.getElementById('np-count').textContent = '';
    document.getElementById('np-imgs').innerHTML = '';
  }

  document.getElementById('sources').innerHTML = (d.sources||[]).map(function(s){
    return row(s.name, s.status, fmtAgo(s.last_polled_ago_seconds));
  }).join('');

  document.getElementById('outputs').innerHTML = (d.outputs||[]).map(function(o){
    var detail = o.ip || (o.port ? ':'+o.port : '') || o.dir || o.device_ip || '';
    return row(o.type, o.status, detail, o.last_error||null);
  }).join('');

  document.getElementById('enrichers').innerHTML = (d.enrichers||[]).map(function(e){
    return row(e.name, e.status, '');
  }).join('');

  var idleSources = d.idle_sources || [];
  document.getElementById('idle').innerHTML = idleSources.length
    ? idleSources.map(function(src){
        var detail = '';
        if (src.wallpapers_loaded != null) detail = src.wallpapers_loaded + ' wallpapers';
        else if (src.videos_loaded != null) detail = src.videos_loaded + ' videos';
        return row(src.type, src.status, detail);
      }).join('')
    : row('none', 'not_configured', '');

  document.getElementById('footer').textContent =
    'Last updated ' + new Date().toLocaleTimeString() + '  \xb7  auto-refresh every 7s';
}

function load(){
  fetch('/health', {headers: {Accept: 'application/json'}})
    .then(function(r){ return r.json(); })
    .then(render)
    .catch(function(){
      var pill = document.getElementById('pill');
      pill.textContent = 'unreachable';
      pill.className = 'pill degraded';
      document.getElementById('footer').textContent = 'Server unreachable — retrying…';
    });
}

load();
setInterval(load, 7000);
</script>
</body>
</html>
"""


class WebOutput(Output):
    def __init__(
        self,
        config: WebConfig,
        rotation_interval_seconds: float = 30,
        cache: Optional[ImageCache] = None,
        auth_config: Optional[AuthConfig] = None,
    ):
        self.config = config
        self.auth_config = auth_config
        self.rotation_interval_seconds = rotation_interval_seconds
        self.transform_pipeline = parse_pipeline(config.transforms)
        self._index_html = (
            _INDEX_HTML
            .replace("/* __TRANSITIONS_CSS__ */", transitions.transitions_css())
            .replace("/* __TRANSITIONS_JS__ */", transitions.transitions_js(config.transition_exclude))
        )
        self._lock = threading.Lock()
        self._now_playing: Optional[NowPlaying] = None
        # Set at construction so idle wallpapers can resolve images even
        # before the first on_new_item() call ever arrives (e.g. nothing
        # has played yet at startup) - on_new_item() keeps this fresh
        # afterward for the (much more common) playing-item case.
        self._cache: Optional[ImageCache] = cache
        self._artwork: Optional[Artwork] = None
        self._image_path: Optional[Path] = None
        self._known_images: Dict[str, Path] = {}

        self._clients_lock = threading.Lock()
        self._clients: set[Any] = set()
        self._client_rotation: Dict[Any, _ClientRotation] = {}
        self._pool_urls: Tuple[str, ...] = ()
        self._shared_order: List[int] = []
        self._next_offset = 0
        self._images_pushed_for_pool = False

        self._health_fn = None
        self.app = self._build_app()
        threading.Thread(target=self._run_server, daemon=True).start()
        threading.Thread(target=self._rotate_clients_loop, daemon=True).start()

    def set_health_provider(self, fn) -> None:
        """Register a callable that returns the health JSON dict for /health."""
        self._health_fn = fn

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        with self._lock:
            self._now_playing = now_playing
            self._artwork = artwork
            self._image_path = image_path
            if image_path is not None:
                self._known_images[image_path.stem] = image_path

        pool_changed = self._maybe_reset_pool(now_playing)
        if pool_changed or not self._images_pushed_for_pool:
            self._push_all_personalized()

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        # Push title/subtitle immediately; the image URL follows in update().
        with self._lock:
            self._now_playing = now_playing
            self._cache = cache
            self._artwork = None
            self._image_path = None
        self._maybe_reset_pool(now_playing)
        self._push(self._get_payload())

    def on_idle(self) -> None:
        with self._lock:
            self._now_playing = None
            self._artwork = None
            self._image_path = None
        self._maybe_reset_pool(None)
        self._push({})

    def _get_payload(self) -> dict:
        """The single "global pick" representation - used for the legacy
        /api/now-playing and as the /image/current fallback. Each
        WebSocket client's actual displayed image is decided independently
        by _personalized_payload(), not this.
        """
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
            "art_label": artwork.label if artwork else "",
        }
        if image_path is not None:
            payload["image"] = f"/image/current?v={image_path.stem}"
        return payload

    # -- per-client rotation ------------------------------------------------

    def _maybe_reset_pool(self, now_playing: Optional[NowPlaying]) -> bool:
        """Reshuffle and reassign every connected client's rotation state
        when the available image pool actually changes (a new item starts,
        an idle batch is refetched, or playback stops) - returns False (and
        leaves existing per-client rotation alone) when called again for
        the same pool, e.g. the orchestrator's own periodic `update()`
        calls for its own single pick within an unchanged item.
        """
        new_urls = tuple(img.url for img in (now_playing.images if now_playing else []))
        with self._clients_lock:
            if new_urls == self._pool_urls:
                return False
            self._pool_urls = new_urls
            self._images_pushed_for_pool = False
            self._shared_order = list(range(len(new_urls)))
            random.shuffle(self._shared_order)
            self._next_offset = 0
            for conn in self._clients:
                self._assign_client_rotation(conn)
        return True

    def _assign_client_rotation(self, conn: Any) -> None:
        """Give one client a position in the current shared order, distinct
        from other clients' (as long as there are at least as many images
        as clients) and a randomly staggered timer phase. Caller must
        already hold _clients_lock.
        """
        if not self._pool_urls:
            self._client_rotation.pop(conn, None)
            return
        num_images = len(self._pool_urls)
        position = self._next_offset % num_images
        self._next_offset += 1
        jitter = random.uniform(0, self.rotation_interval_seconds)
        self._client_rotation[conn] = _ClientRotation(
            order=self._shared_order, position=position, next_due=time.monotonic() - jitter
        )

    def _personalized_payload(self, conn: Any) -> dict:
        with self._lock:
            now_playing = self._now_playing
            cache = self._cache
        if now_playing is None:
            return {}

        with self._clients_lock:
            state = self._client_rotation.get(conn)

        payload: dict = {
            "source": now_playing.source,
            "media_type": now_playing.media_type,
            "title": now_playing.title,
            "subtitle": now_playing.subtitle,
        }
        images = now_playing.images
        if state is not None and images:
            artwork = images[state.order[state.position]]
            payload["art_label"] = artwork.label
            path = self._resolve_artwork_path(
                cache, artwork,
                idle=(now_playing.source == "idle"),
                permanent=(now_playing.media_type == "music"),
            )
            if path is not None:
                with self._lock:
                    self._known_images[path.stem] = path
                payload["image"] = f"/image/current?v={path.stem}"
        return payload

    def _resolve_artwork_path(
        self, cache: Optional[ImageCache], artwork: Artwork, idle: bool, permanent: bool = False
    ) -> Optional[Path]:
        if cache is None:
            return None
        try:
            path = cache.get_path(artwork, idle=idle, permanent=permanent)
            if path is None:
                return None
            return cache.get_transformed_path(path, self.transform_pipeline)
        except Exception:
            logger.exception("Failed to resolve artwork %s", artwork.url)
            return None

    def _push_all_personalized(self) -> None:
        with self._clients_lock:
            clients = list(self._client_rotation.keys())
        for conn in clients:
            self._send_to_one(conn, self._personalized_payload(conn))
        self._images_pushed_for_pool = True

    def _rotate_clients_loop(self) -> None:
        while True:
            time.sleep(_ROTATION_CHECK_INTERVAL_SECONDS)
            try:
                self._rotate_clients_once()
            except Exception:
                # Without this, any unexpected error here (e.g. a bad
                # artwork URL raising somewhere unanticipated) would kill
                # this thread silently and stop per-client rotation for
                # this output forever, with nothing logged.
                logger.exception("Error rotating web output clients")

    def _rotate_clients_once(self) -> None:
        now = time.monotonic()
        due: List[Any] = []
        with self._clients_lock:
            num_images = len(self._pool_urls)
            if num_images <= 1:
                return
            for conn, state in self._client_rotation.items():
                if state.next_due <= now:
                    state.position = (state.position + 1) % num_images
                    state.next_due = now + self.rotation_interval_seconds
                    due.append(conn)
        for conn in due:
            self._send_to_one(conn, self._personalized_payload(conn))

    def _send_to_one(self, conn: Any, payload: dict) -> None:
        try:
            conn.send(json.dumps(payload))
        except Exception:
            with self._clients_lock:
                self._clients.discard(conn)
                self._client_rotation.pop(conn, None)

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
        logger.info("Starting web server on %s:%s", self.config.host, self.config.port)
        self.app.run(host=self.config.host, port=self.config.port, threaded=True)

    def _build_app(self) -> Flask:
        app = Flask(__name__)
        sock = Sock(app)

        @sock.route("/ws")
        def websocket(conn):
            with self._clients_lock:
                self._clients.add(conn)
                self._assign_client_rotation(conn)
            try:
                # Send current state immediately so a fresh page-load or
                # reconnect shows the right content without waiting.
                conn.send(json.dumps(self._personalized_payload(conn)))
                while True:
                    conn.receive()
            except Exception:
                pass
            finally:
                with self._clients_lock:
                    self._clients.discard(conn)
                    self._client_rotation.pop(conn, None)

        @app.get("/")
        def index():
            return self._index_html

        @app.get("/health")
        def health():
            best = request.accept_mimetypes.best_match(
                ["application/json", "text/html"]
            )
            if best == "text/html":
                return _HEALTH_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}
            if self._health_fn is None:
                return jsonify({"status": "starting"})
            return jsonify(self._health_fn())

        @app.get("/api/now-playing")
        def now_playing_json():
            return jsonify(self._get_payload())

        @app.get("/image/current")
        def current_image():
            requested = request.args.get("v")
            with self._lock:
                image_path = self._known_images.get(requested) if requested else None
                if image_path is None:
                    image_path = self._image_path

            if image_path is None or not image_path.exists():
                return "", 404

            return send_file(image_path)

        install_auth(app, self.auth_config)
        return app
