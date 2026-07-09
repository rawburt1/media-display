"""Themes output: a completely separate full-screen display from `web`
(its own port, its own page - see config.example.yaml), that layers
selectable, combinable Display Themes (see mediainfo/themes/) on top of
the current artwork/metadata. Enabled themes render simultaneously into
one combined look (e.g. Vinyl = blurred background + glow + rotation +
palette, all painted into the same page at once), not as alternate
single-active skins - see the Display Themes roadmap plan for the full
design.

Architecturally a sibling of `info`/`web` (same Flask + WebSocket-push
design, see mediainfo/outputs/info.py), broadcasting one shared payload to
every connected browser rather than web.py's independent per-client image
rotation - a themes display isn't "N logical displays sharing one port"
the way the multi-browser web output is designed to be; every connected
browser is expected to show the same themed presentation of the same
now-playing item.

New themes register in mediainfo.registries.THEME_CLASSES (see the Display
Themes roadmap plan's phased delivery) - the client_assets()/prepare()
aggregation plumbing here needs no changes as each one ships.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request, send_file
from flask_sock import Sock
from markupsafe import Markup

from mediainfo.cache import ImageCache
from mediainfo.config import AuthConfig, ThemesConfig
from mediainfo.config.themes import parse_themes
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs import transitions
from mediainfo.outputs.base import Output
from mediainfo.outputs.websocket_push import add_playback_position, broadcast, register_websocket_route
from mediainfo.registries import get_theme_class
from mediainfo.themes.base import DisplayTheme
from mediainfo.transforms import parse_pipeline
from mediainfo.web_auth import install_auth

logger = logging.getLogger(__name__)


class ThemesOutput(Output):
    def __init__(
        self,
        config: ThemesConfig,
        auth_config: Optional[AuthConfig] = None,
        media_data: Optional[MediaDataStore] = None,
    ):
        self.config = config
        self.auth_config = auth_config
        self.media_data = media_data
        self.transform_pipeline = parse_pipeline(config.transforms)
        # Markup: generated CSS/JS is code, not text - autoescaping it
        # would corrupt it (see templates/themes/index.html).
        self._transitions_css = Markup(transitions.transitions_css())
        self._transitions_js = Markup(transitions.transitions_js(config.transition_exclude))

        self._theme_configs: Dict[str, Any] = parse_themes(config.themes)
        self._themes: List[DisplayTheme] = self._build_themes(self._theme_configs)
        self._theme_css = Markup("\n".join(
            assets.css for assets in self._client_assets() if assets.css
        ))
        self._theme_js = Markup("\n".join(
            assets.js for assets in self._client_assets() if assets.js
        ))

        self._lock = threading.Lock()
        self._now_playing: Optional[NowPlaying] = None
        self._artwork: Optional[Artwork] = None
        self._image_path: Optional[Path] = None
        self._cache: Optional[ImageCache] = None
        # stem -> Path, covering both the main resolved image and any
        # derived per-theme composite (see _prepare_themes) - /image/current
        # looks a requested `v` up here, falling back to the main image.
        self._known_images: Dict[str, Path] = {}
        self._clients: set[Any] = set()
        self._clients_lock = threading.Lock()
        self.app = self._build_app()
        threading.Thread(target=self._run_server, daemon=True).start()

    def set_media_data_store(self, store: Optional[MediaDataStore]) -> None:
        """Wired in post-construction by wiring.wire_media_data_store() -
        MediaDataStore is built inside start_orchestrator(), after outputs
        are already instantiated, so it can't be a constructor arg the way
        `config`/`auth_config` are (same reason WebOutput.set_history()/
        set_health_provider() exist as setters rather than constructor
        params). None means no theme needing it (e.g. Word Cloud for
        music) can produce anything until this is called with a real
        store, or config leaves mediadata unconfigured entirely."""
        self.media_data = store

    @staticmethod
    def _build_themes(theme_configs: Dict[str, Any]) -> List[DisplayTheme]:
        """Instantiate every enabled, resolvable theme from the already-
        parsed theme configs - an unknown/unresolvable theme class is
        logged and skipped (matches parse_themes()'s own warn-and-skip-
        unknown-name behavior) rather than failing the whole output,
        since one misconfigured theme shouldn't take down the entire
        display."""
        themes: List[DisplayTheme] = []
        for name, theme_config in theme_configs.items():
            if not getattr(theme_config, "enabled", False):
                continue
            theme_cls = get_theme_class(name)
            if theme_cls is None:
                logger.warning("Themes output: unknown theme %r - skipping", name)
                continue
            themes.append(theme_cls())
        return themes

    def _client_assets(self):
        for theme in self._themes:
            assets = theme.client_assets(self._theme_config_for(theme))
            if assets is not None:
                yield assets

    def _theme_config_for(self, theme: DisplayTheme) -> Any:
        return self._theme_configs.get(theme.name)

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        with self._lock:
            self._now_playing = now_playing
            self._artwork = artwork
            self._image_path = image_path
            if image_path is not None:
                self._known_images[image_path.stem] = image_path
        self._push(self._get_payload())

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        # Push title/subtitle immediately; the image URL (and any
        # per-theme prepare() results, once themes exist) follow in
        # update(), which is where artwork/image_path become known.
        with self._lock:
            self._now_playing = now_playing
            self._cache = cache
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
            cache = self._cache

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

        if artwork is not None and image_path is not None:
            themes_payload = self._prepare_themes(now_playing, artwork, image_path, cache)
            if themes_payload:
                payload["themes"] = themes_payload
        return payload

    def _prepare_themes(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: Optional[ImageCache],
    ) -> dict:
        if cache is None:
            return {}
        result: dict = {}
        for theme in self._themes:
            try:
                rendered = theme.prepare(
                    now_playing, artwork, image_path, cache, self.media_data,
                    self._theme_config_for(theme),
                )
            except Exception:
                logger.exception("Theme %r failed to prepare", theme.name)
                continue
            if rendered is None:
                continue
            entry = dict(rendered.extra_payload)
            if rendered.derived_image_path is not None:
                with self._lock:
                    self._known_images[rendered.derived_image_path.stem] = rendered.derived_image_path
                entry["image"] = f"/image/current?v={rendered.derived_image_path.stem}"
            result[theme.name] = entry
        return result

    def _push(self, payload: dict) -> None:
        broadcast(self._clients_lock, self._clients, payload)

    def _run_server(self) -> None:
        logger.info("Starting themes server on %s:%s", self.config.host, self.config.port)
        self.app.run(host=self.config.host, port=self.config.port, threaded=True)

    def _build_app(self) -> Flask:
        app = Flask(__name__)
        sock = Sock(app)

        register_websocket_route(
            sock, "/ws", self._clients_lock, self._clients,
            get_initial_payload=lambda conn: self._get_payload(),
        )

        @app.get("/")
        def index():
            return render_template(
                "themes/index.html",
                transitions_css=self._transitions_css,
                transitions_js=self._transitions_js,
                theme_css=self._theme_css,
                theme_js=self._theme_js,
            )

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
