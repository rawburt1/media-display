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
import functools
import logging
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, render_template, request, send_file
from flask_sock import Sock
from markupsafe import Markup

from mediainfo.app_services import AppServices
from mediainfo.cache import CacheTier, ImageCache
from mediainfo.config import WebConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs import transitions
from mediainfo.outputs.base import Output
from mediainfo.outputs.websocket_push import (
    CLIENTS,
    add_playback_position,
    broadcast,
    register_websocket_route,
    send_to_one,
    summarize_payload,
)
from mediainfo.imaging.transforms import parse_pipeline

logger = logging.getLogger(__name__)

# The standalone Swedish word clock page (served at /ordklocka, and shown
# in an iframe over the idle screen when WebConfig.idle_clock is on).
_ORDKLOCKA_DIR = Path(__file__).resolve().parent / "static" / "ordklocka"
_ORDKLOCKA_PAGE = _ORDKLOCKA_DIR / "index.html"
# idle_clock_style -> the clock page shown over the idle screen.
_IDLE_CLOCK_URLS = {
    "words": "/ordklocka",
    "split_flap": "/ordklocka/tavla",
    "matrix": "/ordklocka/matrix",
    "eye_chart": "/ordklocka/syntavla",
    "neon": "/ordklocka/neon",
    "fridge_magnets": "/ordklocka/magneter",
    "bus_sign": "/ordklocka/buss",
    "teletext": "/ordklocka/texttv",
    "letter_tiles": "/ordklocka/brickor",
}
# Clock page path -> its label on /clients. Each page has a presence
# WebSocket at <path>/ws (/ordklocka/ws for the word clock).
_CLOCK_LABELS = {
    "/ordklocka": "Ordklocka",
    "/ordklocka/tavla": "Ordklocka (tavla)",
    "/ordklocka/matrix": "Ordklocka (matrix)",
    "/ordklocka/syntavla": "Ordklocka (syntavla)",
    "/ordklocka/neon": "Ordklocka (neon)",
    "/ordklocka/magneter": "Ordklocka (magneter)",
    "/ordklocka/buss": "Ordklocka (busskylt)",
    "/ordklocka/texttv": "Ordklocka (text-tv)",
    "/ordklocka/brickor": "Ordklocka (brickor)",
}
# Clock pages other than /ordklocka itself: path -> file in _ORDKLOCKA_DIR.
_CLOCK_PAGE_FILES = {
    path: path.rsplit("/", 1)[1] + ".html" for path in _CLOCK_LABELS if path != "/ordklocka"
}
# Scripts shared by the clock pages: tid.js (time reading), sida.js (panel,
# presence, ticking), layouts.js (grids for matrix/syntavla) and meny.js
# (the clock picker in every clock page's panel).
_ORDKLOCKA_SCRIPTS = ("tid.js", "sida.js", "layouts.js", "meny.js")
# The only font files /ordklocka/fonts/<name> will serve.
_ORDKLOCKA_FONTS = frozenset({"josefin-sans-latin-600.woff2", "optician-sans.woff2"})

# How often the background thread checks for clients due to rotate to
# their next image. Independent of (and much finer-grained than)
# rotation_interval_seconds, which controls how often any given client
# actually advances.
_ROTATION_CHECK_INTERVAL_SECONDS = 1.0

# Re-send a client its current state when nothing else has been sent to
# it for this long. Idle with no wallpapers (or an item with a single
# image) otherwise sends nothing at all, and the page's stale-connection
# watchdog (STALE_TIMEOUT_MS in templates/web/index.html, 90s minimum)
# would then reload the page every 90s. Re-sending the unchanged state is
# a no-op on the page (same image, same text), so it works as a heartbeat
# even for pages loaded before this existed. Must stay well under 90s.
_HEARTBEAT_INTERVAL_SECONDS = 30.0


@dataclasses.dataclass
class _ClientRotation:
    """One WebSocket client's independent position in a randomized cycle
    through the current NowPlaying.images, shared with other clients only
    via the (read-only, never mutated after creation) `order` list."""

    order: List[int]
    position: int
    next_due: float


def _send_ordklocka_file(name: str, mimetype: str):
    """Serve one of the fixed clock files (never a caller-supplied path)."""
    path = _ORDKLOCKA_DIR / name
    if not path.exists():
        return "Word clock file is missing from this installation", 404
    return send_file(path, mimetype=mimetype)


def _clock_summary(label: str) -> Callable[[dict], Dict[str, str]]:
    """What a standalone clock page shows, for /clients."""
    return lambda payload: {"mode": "clock", "text": label}


class WebOutput(Output):
    name = "web"
    config_class = WebConfig
    # Unlike Pixoo/Nest Hub/etc., the browser page has room (and enough
    # resolution) to show a lyrics word-cloud image legibly - the only
    # output that opts into Artwork.is_wordcloud images (see
    # Output.show_wordclouds and orchestrator_artwork.py).
    show_wordclouds = True

    # Mounts at "/" on the shared HTTP server, not "/web" - see
    # Output.root_mounted and wiring.py.
    root_mounted = True

    def __init__(
        self,
        config: WebConfig,
        rotation_interval_seconds: float = 30,
        cache: Optional[ImageCache] = None,
    ):
        self.config = config
        self.rotation_interval_seconds = rotation_interval_seconds
        self.transform_pipeline = parse_pipeline(config.transforms)
        # Markup: the transitions CSS/JS is code, not text - autoescaping it
        # would corrupt it (see templates/web/index.html).
        self._transitions_css = Markup(transitions.transitions_css())
        self._transitions_js = Markup(transitions.transitions_js(config.transition_exclude))
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
        # conn -> time.monotonic() of the last payload sent to it, for the
        # heartbeat (see _HEARTBEAT_INTERVAL_SECONDS).
        self._last_sent: Dict[Any, float] = {}

        # Standalone /ordklocka pages - connected only so they show up on
        # /clients; never sent anything after their initial payload.
        self._clock_clients_lock = threading.Lock()
        self._clock_clients: set[Any] = set()
        if config.idle_clock_style not in _IDLE_CLOCK_URLS:
            logger.warning(
                "outputs.web.idle_clock_style %r is not one of %s - using the word clock",
                config.idle_clock_style,
                ", ".join(_IDLE_CLOCK_URLS),
            )
        self._idle_clock_url = _IDLE_CLOCK_URLS.get(config.idle_clock_style, "/ordklocka")

        self._health_fn = None
        self._history = None
        threading.Thread(target=self._rotate_clients_loop, daemon=True).start()

    def set_health_provider(self, fn) -> None:
        """Register a callable that returns the health JSON dict for /health."""
        self._health_fn = fn

    def set_history(self, history) -> None:
        """Register the PlaybackHistory store backing the /history page -
        see AppServices.history. None means the feature is disabled."""
        self._history = history

    def attach(self, services: AppServices) -> None:
        self.set_health_provider(services.health_provider)
        self.set_history(services.history)

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
        add_playback_position(payload, now_playing)
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
        # Called on connect (right before the initial payload goes out)
        # and on pool resets (followed by a push) - either way counts as
        # just sent for the heartbeat.
        self._last_sent[conn] = time.monotonic()
        if not self._pool_urls:
            self._client_rotation.pop(conn, None)
            return
        num_images = len(self._pool_urls)
        position = self._next_offset % num_images
        self._next_offset += 1
        jitter = random.uniform(0, self.rotation_interval_seconds)
        self._client_rotation[conn] = _ClientRotation(
            order=self._shared_order,
            position=position,
            next_due=time.monotonic() - jitter,
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
        add_playback_position(payload, now_playing)
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
                self._heartbeat_once()
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

    def _summarize(self, payload: dict) -> Dict[str, str]:
        """What a /ws client shows (for /clients) - with idle_clock on, the
        word clock covers the idle screen."""
        if not self.config.idle_clock:
            return summarize_payload(payload)
        return summarize_payload(payload, idle_label=_CLOCK_LABELS[self._idle_clock_url])

    def _heartbeat_once(self) -> None:
        """Re-send every client that hasn't been sent anything for
        _HEARTBEAT_INTERVAL_SECONDS its current (unchanged) state."""
        cutoff = time.monotonic() - _HEARTBEAT_INTERVAL_SECONDS
        with self._clients_lock:
            due = [c for c in self._clients if self._last_sent.get(c, 0.0) <= cutoff]
        for conn in due:
            self._send_to_one(conn, self._personalized_payload(conn))

    def _drop_client(self, conn: Any) -> None:
        self._client_rotation.pop(conn, None)
        self._last_sent.pop(conn, None)

    def _send_to_one(self, conn: Any, payload: dict) -> None:
        with self._clients_lock:
            self._last_sent[conn] = time.monotonic()
        send_to_one(
            self._clients_lock,
            self._clients,
            conn,
            payload,
            on_drop=self._drop_client,
        )

    def _push(self, payload: dict) -> None:
        now = time.monotonic()
        with self._clients_lock:
            for conn in self._clients:
                self._last_sent[conn] = now
        broadcast(
            self._clients_lock,
            self._clients,
            payload,
            on_drop=self._drop_client,
        )

    def build_http_blueprint(self, url_prefix: str, sock: Optional[Sock] = None) -> Blueprint:
        bp = Blueprint("web", __name__)

        if sock is not None:
            register_websocket_route(
                sock,
                "/ws",
                self._clients_lock,
                self._clients,
                get_initial_payload=self._personalized_payload,
                on_connect=self._assign_client_rotation,
                on_disconnect=self._drop_client,
                bp=bp,
                summarize=self._summarize,
            )
            for page, label in _CLOCK_LABELS.items():
                register_websocket_route(
                    sock,
                    page + "/ws",
                    self._clock_clients_lock,
                    self._clock_clients,
                    get_initial_payload=lambda conn: {},
                    bp=bp,
                    summarize=_clock_summary(label),
                )

        @bp.get("/")
        def index():
            return render_template(
                "web/index.html",
                transitions_css=self._transitions_css,
                transitions_js=self._transitions_js,
                rotation_interval_seconds=self.rotation_interval_seconds,
                idle_clock=self.config.idle_clock,
                idle_clock_url=self._idle_clock_url,
            )

        @bp.get("/ordklocka")
        def ordklocka():
            # Served as-is (not via render_template) - it's a self-contained
            # page, and its CSS/JS mustn't be run through Jinja.
            if not _ORDKLOCKA_PAGE.exists():
                return "Word clock page is missing from this installation", 404
            return send_file(_ORDKLOCKA_PAGE, mimetype="text/html")

        for path, file_name in _CLOCK_PAGE_FILES.items():
            bp.add_url_rule(
                path,
                endpoint="ordklocka_" + file_name.removesuffix(".html"),
                view_func=functools.partial(_send_ordklocka_file, file_name, "text/html"),
            )
        for script in _ORDKLOCKA_SCRIPTS:
            bp.add_url_rule(
                "/ordklocka/" + script,
                endpoint="ordklocka_" + script.replace(".", "_"),
                view_func=functools.partial(_send_ordklocka_file, script, "text/javascript"),
            )

        @bp.get("/ordklocka/fonts/<name>")
        def ordklocka_font(name: str):
            if name not in _ORDKLOCKA_FONTS:
                return "Not found", 404
            return _send_ordklocka_file("fonts/" + name, "font/woff2")

        @bp.get("/clients")
        def clients_page():
            return render_template("web/clients.html")

        @bp.get("/api/clients")
        def clients_json():
            return jsonify({"clients": CLIENTS.snapshot(), "now": time.time()})

        @bp.get("/health/live")
        def health_live():
            return jsonify({"status": "ok"})

        @bp.get("/health/ready")
        @bp.get("/health")
        def health():
            best = request.accept_mimetypes.best_match(["application/json", "text/html"])
            if best == "text/html":
                return render_template("web/health.html")
            if self._health_fn is None:
                return jsonify({"status": "starting"})
            return jsonify(self._health_fn())

        @bp.get("/api/now-playing")
        def now_playing_json():
            return jsonify(self._get_payload())

        @bp.get("/history")
        def history_page():
            return render_template("web/history.html")

        @bp.get("/api/history")
        def history_json():
            if self._history is None:
                return jsonify({"enabled": False, "items": []})
            try:
                limit = int(request.args.get("limit", 50))
            except ValueError:
                limit = 50
            return jsonify({"enabled": True, "items": self._history.list(limit)})

        @bp.get("/history/image/<int:entry_id>")
        def history_image(entry_id: int):
            """Thumbnail for one history entry, resolved through the
            regular artwork cache by the entry's stored URL - usually a
            plain cache hit, since the artwork was fetched when the item
            played."""
            if self._history is None or self._cache is None:
                return "", 404
            entry = self._history.entry_artwork(entry_id)
            if entry is None:
                return "", 404
            url, media_type = entry
            tier: CacheTier = "music" if media_type == "music" else "default"
            try:
                path = self._cache.get_path(Artwork(url=url), tier=tier)
            except Exception:
                logger.exception("Failed to resolve history artwork %s", url)
                return "", 404
            if path is None or not path.exists():
                return "", 404
            return send_file(path)

        @bp.get("/image/current")
        def current_image():
            requested = request.args.get("v")
            with self._lock:
                image_path = self._known_images.get(requested) if requested else None
                if image_path is None:
                    image_path = self._image_path

            if image_path is None or not image_path.exists():
                return "", 404

            return send_file(image_path)

        return bp
