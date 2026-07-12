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
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from flask import Flask, jsonify, render_template, request, send_file
from flask_sock import Sock
from markupsafe import Markup

from mediainfo.app_services import AppServices
from mediainfo.cache import ImageCache
from mediainfo.config import AuthConfig, AutoRotatePresetConfig, ThemesConfig
from mediainfo.config.outputs import parse_presets
from mediainfo.config.themes import parse_themes
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs import transitions
from mediainfo.outputs.base import Output
from mediainfo.outputs.websocket_push import (
    add_playback_position,
    broadcast,
    register_websocket_route,
)
from mediainfo.registries import get_theme_class
from mediainfo.themes.base import DisplayTheme
from mediainfo.transforms import parse_pipeline
from mediainfo.web_auth import install_auth

logger = logging.getLogger(__name__)

# NowPlaying.media_type is "music" | "movie" | "episode" for real playback,
# and "wallpaper" for idle wallpapers (see orchestrator_idle.py's
# NowPlaying(..., media_type="wallpaper", ...) construction sites - the
# model's own type comment doesn't mention this case). AutoRotatePresetConfig
# .when uses the friendlier "idle" instead; this is the only place that
# translation happens - nothing else compares against "idle"/"wallpaper".
_IDLE_MEDIA_TYPE_ALIAS = {"idle": "wallpaper"}


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
        self._theme_css = Markup(
            "\n".join(assets.css for assets in self._client_assets() if assets.css)
        )
        self._theme_js = Markup(
            "\n".join(assets.js for assets in self._client_assets() if assets.js)
        )

        self._lock = threading.Lock()
        self._now_playing: Optional[NowPlaying] = None
        self._artwork: Optional[Artwork] = None
        self._image_path: Optional[Path] = None
        # update() copies image_path into this directory (keeping its
        # original filename/stem, so the public /image/current?v=<stem> URL
        # and _known_images keys are unaffected) so _get_payload() (and thus
        # _prepare_themes()/theme.prepare()) can still read it whenever it's
        # next called - a WebSocket client connecting, or /api/now-playing
        # being polled, both call it fully decoupled in time from the
        # original update(). For idle wallpapers, the caller
        # (orchestrator_idle) deletes the original image_path immediately
        # after update() returns - see update() below, same reasoning/
        # pattern as NestHubOutput.update()'s own copy-before-the-caller-
        # deletes-it.
        self._owned_image_dir = Path(tempfile.mkdtemp(prefix="mediainfo-themes-"))
        self._owned_image_path: Optional[Path] = None
        self._cache: Optional[ImageCache] = None
        # stem -> Path, covering both the main resolved image and any
        # derived per-theme composite (see _prepare_themes) - /image/current
        # looks a requested `v` up here, falling back to the main image.
        self._known_images: Dict[str, Path] = {}
        self._clients: set[Any] = set()
        self._clients_lock = threading.Lock()

        # Auto-rotate (see config.AutoRotateConfig / _active_theme_names):
        # presets split into two groups. _rotation_pool holds unconditioned
        # presets (no `when`) in stable config order - the timer-rotation
        # pool, exactly like every preset before `when` existed. _conditioned
        # holds presets that do have a `when`, each paired with its
        # alias-normalized media-type set - checked first, on every payload,
        # against whatever's currently playing (see _current_preset_name());
        # a match is pinned and the timer never rotates away from it. Both
        # empty/None when disabled or no presets are configured, which is
        # what _current_preset_name() checks to fall back to "show every
        # enabled theme" - today's pre-Phase-8 behavior.
        self._presets: Dict[str, AutoRotatePresetConfig] = (
            parse_presets(config.auto_rotate.presets) if config.auto_rotate.enabled else {}
        )
        self._rotation_pool: List[str] = [
            name for name, preset in self._presets.items() if not preset.when
        ]
        self._conditioned: List[Tuple[str, Set[str]]] = [
            (name, {_IDLE_MEDIA_TYPE_ALIAS.get(mt, mt) for mt in preset.when})
            for name, preset in self._presets.items()
            if preset.when
        ]
        self._active_preset: Optional[str] = self._rotation_pool[0] if self._rotation_pool else None
        self._warn_preset_issues()
        if self._rotation_pool:
            threading.Thread(target=self._auto_rotate_loop, daemon=True).start()

        self.app = self._build_app()
        threading.Thread(target=self._run_server, daemon=True).start()

    def _warn_preset_issues(self) -> None:
        enabled_names = {theme.name for theme in self._themes}
        for preset_name, preset in self._presets.items():
            unknown = [n for n in preset.themes if n not in enabled_names]
            if unknown:
                logger.warning(
                    "Themes output: auto_rotate preset %r names theme(s) %s that "
                    "aren't enabled - they'll never appear while this preset is active",
                    preset_name,
                    unknown,
                )

        claimed: Dict[str, str] = {}
        for preset_name, when_set in self._conditioned:
            for media_type in when_set:
                first_preset = claimed.get(media_type)
                if first_preset is None:
                    claimed[media_type] = preset_name
                else:
                    logger.warning(
                        "Themes output: auto_rotate preset %r also claims media "
                        "type %r, already claimed by preset %r - %r wins for that "
                        "media type (first one declared in config)",
                        preset_name,
                        media_type,
                        first_preset,
                        first_preset,
                    )

    def set_media_data_store(self, store: Optional[MediaDataStore]) -> None:
        """Wired in post-construction by attach() (see AppServices.
        mediadata_store) - MediaDataStore is built inside
        start_orchestrator(), after outputs are already instantiated, so
        it can't be a constructor arg the way `config`/`auth_config` are
        (same reason WebOutput.set_history()/set_health_provider() exist
        as setters rather than constructor params). None means no theme
        needing it (e.g. Word Cloud for music) can produce anything until
        this is called with a real store, or config leaves mediadata
        unconfigured entirely."""
        self.media_data = store

    def attach(self, services: AppServices) -> None:
        self.set_media_data_store(services.mediadata_store)

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

    def _auto_rotate_loop(self) -> None:
        interval = max(1, self.config.auto_rotate.interval_seconds)
        while True:
            time.sleep(interval)
            self._advance_preset()

    def _advance_preset(self) -> None:
        """Move to the next preset in the rotation pool (wrapping around)
        and push the re-filtered payload - split out from
        _auto_rotate_loop so tests can trigger a rotation directly instead
        of sleeping. Only ever touches the unconditioned rotation pool - a
        conditioned preset currently pinned (see _current_preset_name)
        overrides whatever this pointer is doing, so the pointer is free
        to keep ticking silently in the background; once the pin lifts,
        display just resumes wherever the pool already advanced to."""
        with self._lock:
            # Invariant: whenever _rotation_pool is non-empty (the only
            # time this method runs), _active_preset is always one of its
            # members - set from _rotation_pool[0] at construction and
            # only ever reassigned here, to another _rotation_pool member.
            assert self._active_preset is not None
            idx = self._rotation_pool.index(self._active_preset)
            self._active_preset = self._rotation_pool[(idx + 1) % len(self._rotation_pool)]
        self._push(self._get_payload())

    def _current_preset_name(self) -> Optional[str]:
        """The preset actually governing the payload right now: a
        conditioned preset whose `when` matches the current media type
        (first one declared in config wins - see _warn_preset_issues),
        else the rotation pool's current pointer, else None (no filtering
        - show every enabled theme, auto-rotate off or nothing configured)."""
        if not self._presets:
            return None
        with self._lock:
            active_preset = self._active_preset
            now_playing = self._now_playing
        media_type = now_playing.media_type if now_playing is not None else None
        if media_type is not None:
            for name, when_set in self._conditioned:
                if media_type in when_set:
                    return name
        return active_preset

    def _active_theme_names(self) -> Optional[Set[str]]:
        """The theme names allowed in the outgoing payload right now, or
        None to mean "no filtering - include every prepared theme"."""
        preset_name = self._current_preset_name()
        if preset_name is None:
            return None
        return set(self._presets[preset_name].themes)

    def _client_assets(self):
        for theme in self._themes:
            assets = theme.client_assets(self._theme_config_for(theme))
            if assets is not None:
                yield assets

    def _theme_config_for(self, theme: DisplayTheme) -> Any:
        return self._theme_configs.get(theme.name)

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        # Copy to a file we manage ourselves - see _owned_image_dir above
        # for why. Keeps image_path's own filename (rather than a fresh
        # random one) so the public /image/current?v=<stem> URL stays the
        # same as before this copy existed - stable/content-addressable for
        # regular playback (image_path.stem is already a content hash - see
        # ImageCache.get_path()), and simply whatever name download_temp()
        # gave it for idle wallpapers.
        stable_path: Optional[Path] = None
        if image_path is not None:
            stable_path = self._owned_image_dir / image_path.name
            shutil.copy2(image_path, stable_path)

        with self._lock:
            old_owned_path = self._owned_image_path
            self._now_playing = now_playing
            self._artwork = artwork
            self._image_path = stable_path
            self._owned_image_path = stable_path
            if stable_path is not None:
                self._known_images[stable_path.stem] = stable_path
        # Same image re-pushed (e.g. a rotation re-push of an unchanged
        # item) copies over itself - only unlink a *different*, superseded
        # file, never the one we just wrote.
        if old_owned_path is not None and old_owned_path != stable_path:
            old_owned_path.unlink(missing_ok=True)
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
        preset_name = self._current_preset_name()
        if preset_name is not None:
            payload["active_preset"] = preset_name

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
        # Every enabled theme still prepares every tick regardless of the
        # active auto-rotate preset (see _active_theme_names) - only which
        # entries make it into `result` is filtered below, so rotating
        # presets is instant and never waits on prepare() to catch up.
        active_names = self._active_theme_names()
        result: dict = {}
        for theme in self._themes:
            try:
                rendered = theme.prepare(
                    now_playing,
                    artwork,
                    image_path,
                    cache,
                    self.media_data,
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
                    self._known_images[rendered.derived_image_path.stem] = (
                        rendered.derived_image_path
                    )
                entry["image"] = f"/image/current?v={rendered.derived_image_path.stem}"
            if rendered.derived_image_paths:
                with self._lock:
                    for path in rendered.derived_image_paths:
                        self._known_images[path.stem] = path
            if active_names is not None and theme.name not in active_names:
                continue
            result[theme.name] = entry
        return result

    def health_check(self) -> Optional[dict]:
        """Aggregates each enabled theme's own health_detail() (e.g.
        Timeline reporting "no discography - showing current album only"
        when Lidarr isn't configured) into {"themes": {name: detail}} -
        picked up automatically for the system-wide /health JSON by
        health.make_health_provider's generic `output.health_check()`
        call for every output, no separate /health route needed here."""
        degraded: Dict[str, dict] = {}
        for theme in self._themes:
            try:
                detail = theme.health_detail(self._theme_config_for(theme))
            except Exception:
                logger.exception("Theme %r failed to report health", theme.name)
                continue
            if detail:
                degraded[theme.name] = detail
        return {"themes": degraded} if degraded else None

    def _push(self, payload: dict) -> None:
        broadcast(self._clients_lock, self._clients, payload)

    def _run_server(self) -> None:
        logger.info("Starting themes server on %s:%s", self.config.host, self.config.port)
        self.app.run(host=self.config.host, port=self.config.port, threaded=True)

    def _build_app(self) -> Flask:
        app = Flask(__name__)
        sock = Sock(app)

        register_websocket_route(
            sock,
            "/ws",
            self._clients_lock,
            self._clients,
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
