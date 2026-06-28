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
import logging
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request, send_file
from flask_sock import Sock

from mediainfo.cache import CacheTier, ImageCache
from mediainfo.config import AuthConfig, WebConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs import transitions
from mediainfo.outputs.base import Output
from mediainfo.outputs.web_templates import _HEALTH_HTML, _INDEX_HTML
from mediainfo.outputs.websocket_push import broadcast, register_websocket_route, send_to_one
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
        """Build this client's payload - falling through the rest of its
        rotation order (in position order, wrapping around) if its current
        pick fails to resolve (e.g. rejected by the cache's minimum-size
        filter), rather than sending a payload with no image at all and
        leaving the client's display blank until its next scheduled
        rotation, up to rotation_interval_seconds later.
        """
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
            tier: CacheTier
            if now_playing.source == "idle":
                tier = "idle"
            elif now_playing.media_type == "music":
                tier = "music"
            else:
                tier = "default"

            for attempt in range(len(images)):
                artwork = images[state.order[(state.position + attempt) % len(state.order)]]
                path = self._resolve_artwork_path(cache, artwork, tier)
                if path is None:
                    continue
                payload["art_label"] = artwork.label
                with self._lock:
                    self._known_images[path.stem] = path
                payload["image"] = f"/image/current?v={path.stem}"
                break
        return payload

    def _resolve_artwork_path(
        self, cache: Optional[ImageCache], artwork: Artwork, tier: CacheTier = "default"
    ) -> Optional[Path]:
        if cache is None:
            return None
        try:
            path = cache.get_path(artwork, tier=tier)
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
        send_to_one(
            self._clients_lock, self._clients, conn, payload,
            on_drop=lambda c: self._client_rotation.pop(c, None),
        )

    def _push(self, payload: dict) -> None:
        broadcast(
            self._clients_lock, self._clients, payload,
            on_drop=lambda c: self._client_rotation.pop(c, None),
        )

    def _run_server(self) -> None:
        logger.info("Starting web server on %s:%s", self.config.host, self.config.port)
        self.app.run(host=self.config.host, port=self.config.port, threaded=True)

    def _build_app(self) -> Flask:
        app = Flask(__name__)
        sock = Sock(app)

        register_websocket_route(
            sock, "/ws", self._clients_lock, self._clients,
            get_initial_payload=self._personalized_payload,
            on_connect=self._assign_client_rotation,
            on_disconnect=lambda conn: self._client_rotation.pop(conn, None),
        )

        @app.get("/")
        def index():
            return self._index_html

        @app.get("/health/live")
        def health_live():
            return jsonify({"status": "ok"})

        @app.get("/health/ready")
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
