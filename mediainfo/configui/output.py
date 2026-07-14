"""Config output: a guided web UI for configuring mediainfo without needing
to know YAML - plus an "Advanced" raw-YAML editor for anything the guided
UI doesn't cover.

This module owns the ConfigUiOutput Output plugin, Flask app/routes, and
the small bits of state (health/hitster-safe callbacks, restart_required,
overview computation) tightly coupled to serving those routes. It composes
three collaborators split into their own modules: config_schema.py (form
schema generation and per-output filter helpers), config_store.py (reading
and saving config.yaml), and appletv_pairing.py (the Apple TV pairing
wizard) - plus the tiny config_yaml_io.py shared by the latter two.

"/" serves the single Dashboard shell (templates/config_ui/dashboard.html,
static/config_ui/dashboard.{js,css,components.js,advanced.js} - see
_dashboard_shell() below), including its in-shell "Advanced" section (raw
YAML editor, config backups/download, and the auth/logging/general
settings cards). H5 (docs/architecture-usability-review-2026-07.md)
finished the two-shell migration ADR 0001 describes - the older classic
shell (templates/config_ui/app.html) is gone. The guided form is generated
from the registered source/output/enricher/idle config dataclasses, so any
config type added there automatically gets a card. Secrets never reach the
browser in cleartext; saving always validates via Config.from_dict() before
writing; `outputs`/`auth` changes need a restart (see _restart_required)
while everything else hot-reloads.

For the full rationale behind these choices - why the form is schema-
driven, the secret-handling wire protocol, restart-required semantics, and
the append-only multi-instance ordering constraint - see
docs/adr/0001-config-ui-two-shell-migration-and-request-lifecycle.md (the
two-shell part of that ADR is now historical).

This output has write access to config.yaml, including any credentials in
it, with no authentication of its own - see SECURITY.md before exposing it
beyond a trusted local network.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import io
import json
import logging
import os
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, redirect, render_template, request, send_file
from PIL import Image, UnidentifiedImageError

import mediainfo.outputs
from mediainfo.app_services import AppServices
from mediainfo.stores.artwork_overrides import ArtworkOverrideStore
from mediainfo.cache import ImageCache, flatten_transparency
from mediainfo.config import (
    ENRICHER_CONFIG_TYPES,
    IDLE_CONFIG_TYPES,
    OUTPUT_CONFIG_TYPES,
    SOURCE_CONFIG_TYPES,
    AuthConfig,
    Config,
    ConfigUiConfig,
)
from mediainfo.config_backup import list_backups
from mediainfo.imaging.led_image import _crop_square, prepare_led_image
from mediainfo.imaging.text_removal import maybe_remove_text
from mediainfo.models import Artwork, NowPlaying
from mediainfo.stores.musiclibrary import MusicLibrary
from mediainfo.configui.appletv_pairing import AppleTvPairingManager
from mediainfo.outputs.base import Output
from mediainfo.configui.config_dashboard import test_enricher, test_output, test_source
from mediainfo.configui.config_schema import (
    _HIDDEN_TYPE_CATEGORIES,
    _as_instance_list,
    _build_schema,
)
from mediainfo.configui.config_store import ConfigStore
from mediainfo.configui.config_yaml_io import _read_config
from mediainfo.configui.ui_builder import (
    build_components,
    build_dashboard,
    build_pipeline,
)
from mediainfo.web_auth import is_loopback_address

logger = logging.getLogger(__name__)

# Give the HTTP response time to reach the browser before this process
# receives SIGTERM and starts shutting down.
_RESTART_DELAY_SECONDS = 0.5

# The config UI's own static assets (JS/CSS) stayed at their original
# location under mediainfo/outputs/ when this module moved to
# mediainfo/configui/ (M6) - anchored off mediainfo.outputs' own file
# location (stable regardless of where this module lives) rather than a
# path relative to this file, which would otherwise silently break
# Blueprint's static-file serving. See build_http_blueprint() below.
_STATIC_DIR = Path(mediainfo.outputs.__file__).resolve().parent / "static" / "config_ui"


def _restart_process() -> None:
    logger.info("Restarting (SIGTERM to self) - requested via the config UI")
    os.kill(os.getpid(), signal.SIGTERM)


class ConfigUiOutput(Output):
    name = "config"
    config_class = ConfigUiConfig
    handles_images = False

    def __init__(
        self,
        config: ConfigUiConfig,
        config_path: Path,
        auth_config: Optional[AuthConfig] = None,
        http_host: str = "0.0.0.0",
    ):
        self.config = config
        self.auth_config = auth_config
        # The shared HTTP server's bind host (see
        # mediainfo/outputs/http_server.py) - kept here (unlike every other
        # output) only for _is_exposed_without_auth()'s warning-banner
        # logic, now that this output no longer has its own host to check.
        self.http_host = http_host
        self.config_path = Path(config_path)
        self._lock = threading.Lock()
        self._store = ConfigStore(self.config_path, self._lock)
        self._appletv = AppleTvPairingManager(
            config_path=self.config_path,
            lock=self._lock,
            run_async=self._run_appletv_async,
            stop_loop=self._stop_appletv_loop,
        )
        self._library: Optional[MusicLibrary] = None
        self._library_db_path: Optional[str] = None
        self._health_fn = None
        self._hitster_safe_get = None
        self._hitster_safe_set = None
        self._overrides: Optional[ArtworkOverrideStore] = None
        # Every other live HTTP output's own top-level page, for the
        # dashboard's quick-open links - see AppServices.page_links.
        self._page_links: list = []
        # Set whenever a form save touches `outputs` (the one category that
        # needs a restart to take effect, since outputs are only
        # instantiated once at startup) - see the "Restart needed" banner
        # on the Overview page (/api/overview). Cleared when /api/restart
        # is called.
        self._restart_required = False
        # Set by build_http_blueprint() once wiring.py has computed it -
        # threaded into templates so their JS can prefix its own fetch()
        # calls (see static/config_ui/*.js).
        self._url_prefix = ""

    def set_hitster_safe_handlers(self, get_fn, set_fn) -> None:
        """Register the orchestrator's Hitster-safe get/set, so this
        output's button can read and toggle it - see
        Orchestrator.get_hitster_safe."""
        self._hitster_safe_get = get_fn
        self._hitster_safe_set = set_fn

    def set_artwork_overrides(self, store: Optional[ArtworkOverrideStore]) -> None:
        """Register the artwork override store, so the "Overrides" page
        can list/add/remove pins - see AppServices.overrides. None means
        the feature is disabled (overrides.enabled: false)."""
        self._overrides = store

    def set_health_provider(self, fn) -> None:
        """Register a callable that returns the health JSON dict - used by
        the System status section and the Overview page's now-playing/
        active-source summary."""
        self._health_fn = fn

    def set_page_links(self, page_links: list) -> None:
        """Register every other live HTTP output's own top-level page, so
        the dashboard can render quick-open links to them - see
        AppServices.page_links and ui_builder.build_dashboard()."""
        self._page_links = page_links

    def attach(self, services: AppServices) -> None:
        commands = services.commands
        self.set_hitster_safe_handlers(
            commands.get_hitster_safe if commands else None,
            commands.set_hitster_safe if commands else None,
        )
        self.set_artwork_overrides(services.overrides)
        self.set_health_provider(services.health_provider)
        self.set_page_links(services.page_links)

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        pass

    def on_idle(self) -> None:
        pass

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        pass

    # -- request handling -------------------------------------------------

    def _get_library(self) -> MusicLibrary:
        """Lazily open (or reopen, if config.yaml's library.db_path
        changed) a MusicLibrary connection for the library browser.

        Independent of the orchestrator's own MusicLibrary instance -
        this output is created once and outlives config reloads, so it
        manages its own connection rather than holding a reference that
        could be closed out from under it by a reload.
        """
        with self._lock:
            data = _read_config(self.config_path)
        library_cfg = data.get("library") or {}
        db_path = library_cfg.get("db_path", "./library/library.db")
        if self._library is None or self._library_db_path != db_path:
            if self._library is not None:
                self._library.close()
            self._library = MusicLibrary(db_path, max_age_days=library_cfg.get("max_age_days", 30))
            self._library_db_path = db_path
        return self._library

    def _compute_overview(self) -> Dict[str, Any]:
        """Data for the Overview page: health summary, enabled-item counts,
        and the two "needs your attention" flags this output can determine
        by itself (outputs-need-restart, exposed-without-auth) - everything
        else (missing required settings, priority warnings, per-item
        unreachable status) is derived client-side from /api/schema,
        /api/config, and /api/status, which already carry what's needed.
        """
        with self._lock:
            data = _read_config(self.config_path)

        def _count_enabled(category: str, registry: Dict[str, type]) -> int:
            section = data.get(category) or {}
            return sum(
                1
                for name in registry
                if isinstance(section.get(name), dict) and section[name].get("enabled")
            )

        def _count_enabled_outputs() -> int:
            section = data.get("outputs") or {}
            count = 0
            for name in OUTPUT_CONFIG_TYPES:
                for instance in _as_instance_list(section.get(name)):
                    if isinstance(instance, dict) and instance.get("enabled"):
                        count += 1
            return count

        counts = {
            "sources_enabled": _count_enabled("sources", SOURCE_CONFIG_TYPES),
            "outputs_enabled": _count_enabled_outputs(),
            "enrichers_enabled": _count_enabled("enrichers", ENRICHER_CONFIG_TYPES),
            "idle_enabled": _count_enabled("idle", IDLE_CONFIG_TYPES),
        }

        now_playing = None
        active_source = None
        if self._health_fn is not None:
            health = self._health_fn()
            now_playing = health.get("now_playing")
            for s in health.get("sources", []):
                if s.get("status") == "active":
                    active_source = s.get("name")
                    break

        return {
            "now_playing": now_playing,
            "active_source": active_source,
            "counts": counts,
            "restart_required": self._restart_required,
            "exposed_without_auth": self._is_exposed_without_auth(),
        }

    def _is_exposed_without_auth(self) -> bool:
        """Whether this instance is bound somewhere reachable beyond this
        machine (host isn't loopback) with no login required - independent
        of any single request's own address (unlike _show_auth_warning,
        which is about whether *this visitor* should see the banner)."""
        auth_on = bool(self.auth_config and self.auth_config.enabled)
        return (
            not is_loopback_address(self.http_host)
            and self.http_host != "localhost"
            and not auth_on
        )

    def _build_ui_components(self):
        """Backend for /api/ui/* - translates the same schema/config/health
        data _build_schema()/ConfigStore/self._health_fn already expose into
        the ui_model.UiComponent list (see ui_builder.py). Read-only, adds
        no new config reading/writing path."""
        with self._lock:
            data = _read_config(self.config_path)
        schema = _build_schema()
        values, secrets_set = self._store.get_values()
        output_instances, output_secrets_set = self._store.get_output_instances()
        text_enrichers_raw = data.get("text_enrichers") or {}
        health = self._health_fn() if self._health_fn is not None else None
        return build_components(
            schema,
            values,
            secrets_set,
            output_instances,
            output_secrets_set,
            text_enrichers_raw,
            health,
        )

    def _build_ui_dashboard(self):
        components = self._build_ui_components()
        pipeline = build_pipeline(components)
        health = self._health_fn() if self._health_fn is not None else None
        return (
            components,
            pipeline,
            build_dashboard(
                components,
                pipeline,
                self._compute_overview(),
                health,
                self._page_links,
            ),
        )

    # -- Apple TV pairing ---------------------------------------------
    #
    # The pairing state machine itself lives in AppleTvPairingManager
    # (composed as self._appletv above); _run_appletv_async/
    # _stop_appletv_loop stay defined here and are injected into it,
    # since tests monkeypatch these two names directly on this class.

    @staticmethod
    def _run_appletv_async(loop: asyncio.AbstractEventLoop, coro, timeout: float = 30) -> Any:
        """Run `coro` on `loop` (which belongs to a different thread) and
        block this thread until it completes. Split out so tests can
        monkeypatch it to use asyncio.run() instead of a real background
        loop+thread.
        """
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    @staticmethod
    def _stop_appletv_loop(loop: asyncio.AbstractEventLoop, thread: threading.Thread) -> None:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()

    def _show_auth_warning(self) -> bool:
        """Whether the config form should show its auth-warning banner (see
        templates/config_ui/dashboard.html): shown to any non-loopback caller
        when auth is off, because the config form has read+write access to
        config.yaml including all stored credentials.
        """
        if self.auth_config and self.auth_config.enabled:
            return False
        return not is_loopback_address(request.remote_addr)

    def build_http_blueprint(self, url_prefix: str, sock=None) -> Blueprint:
        self._url_prefix = url_prefix
        bp = Blueprint(
            "config",
            __name__,
            # Absolute, not "static/config_ui" - a Blueprint's relative
            # static_folder resolves against *this module's own* file
            # location, which is mediainfo/configui/ (M6 in
            # docs/architecture-usability-review-2026-07.md moved the
            # config UI's Python backend there, but deliberately left its
            # Jinja templates/static assets under mediainfo/outputs/,
            # where every other output's own templates/static already
            # live - see _STATIC_DIR above).
            static_folder=str(_STATIC_DIR),
            static_url_path="/static",
        )

        def _dashboard_shell():
            return render_template(
                "config_ui/dashboard.html",
                show_auth_warning=self._show_auth_warning(),
                url_prefix=url_prefix,
            )

        @bp.get("/")
        def index():
            # H5 (docs/architecture-usability-review-2026-07.md) finished
            # the two-shell migration from ADR 0001: the classic app.html
            # shell is gone, so this is now the only shell regardless of
            # `ui` - that field is kept only so existing config.yaml files
            # that set it don't fail to load.
            return _dashboard_shell()

        # /form and /dashboard predate the single-shell nav (ADR 0001) -
        # kept as redirects so anyone with either bookmarked still lands
        # somewhere useful instead of a 404.
        @bp.get("/form")
        def form_page():
            return redirect(f"{url_prefix}/#advanced")

        @bp.get("/dashboard")
        def dashboard_page():
            return _dashboard_shell()

        @bp.get("/api/schema")
        def schema():
            return jsonify(_build_schema())

        @bp.get("/api/config")
        def get_config():
            with self._lock:
                raw_yaml = (
                    self.config_path.read_text(encoding="utf-8")
                    if self.config_path.exists()
                    else ""
                )
            values, values_secrets = self._store.get_values()
            outputs, output_secrets = self._store.get_output_instances()
            return jsonify(
                {
                    "values": values,
                    "outputs": outputs,
                    "raw_yaml": raw_yaml,
                    "secrets_set": {**values_secrets, **output_secrets},
                    "hidden_types": self._store.get_hidden_types(),
                }
            )

        @bp.get("/api/overview")
        def overview():
            return jsonify(self._compute_overview())

        # -- New UI model endpoints (Fas 1 of the GUI redesign) -----------
        # Read-only translations of the same schema/config/health data the
        # routes above already expose - see ui_builder.py. Additive: none
        # of the routes above change.

        @bp.get("/api/ui/components")
        def ui_components():
            components = self._build_ui_components()
            return jsonify([dataclasses.asdict(c) for c in components])

        @bp.get("/api/ui/component/<id>")
        def ui_component(id: str):
            components = self._build_ui_components()
            for c in components:
                if c.id == id:
                    return jsonify(dataclasses.asdict(c))
            return jsonify({"error": f"Unknown component id: {id}"}), 404

        @bp.get("/api/ui/pipelines")
        def ui_pipelines():
            components = self._build_ui_components()
            pipeline = build_pipeline(components)
            return jsonify([dataclasses.asdict(pipeline)])

        @bp.get("/api/ui/dashboard")
        def ui_dashboard():
            _components, _pipeline, dashboard = self._build_ui_dashboard()
            return jsonify(dataclasses.asdict(dashboard))

        @bp.post("/api/config/form")
        def save_form():
            body = request.get_json(silent=True) or {}
            error, restart_required = self._store.save_form(
                body.get("values") or {}, body.get("outputs") or {}
            )
            if error:
                return jsonify({"ok": False, "error": error}), 400
            if restart_required:
                self._restart_required = True
            return jsonify({"ok": True, "restart_required": self._restart_required})

        @bp.post("/api/config/raw")
        def save_raw():
            body = request.get_json(silent=True) or {}
            error, restart_required = self._store.save_raw(body.get("yaml") or "")
            if error:
                return jsonify({"ok": False, "error": error}), 400
            if restart_required:
                self._restart_required = True
            return jsonify({"ok": True, "restart_required": self._restart_required})

        @bp.post("/api/config/hidden-types")
        def set_hidden_type():
            body = request.get_json(silent=True) or {}
            category = body.get("category")
            name = body.get("name")
            hidden = bool(body.get("hidden"))
            if category not in _HIDDEN_TYPE_CATEGORIES or not isinstance(name, str) or not name:
                return jsonify({"ok": False, "error": "Invalid category or name."}), 400
            error = self._store.set_hidden_type(category, name, hidden)
            if error:
                return jsonify({"ok": False, "error": error}), 400
            return jsonify({"ok": True, "hidden_types": self._store.get_hidden_types()})

        @bp.get("/api/config/download")
        def download_config():
            # Same file /api/config's raw_yaml field already reads, just
            # served as an actual attachment instead of embedded in JSON -
            # no new read/validation path. Secrets aren't masked here
            # (unlike every other route) since this hands back the literal
            # file a restore would need, credentials included - matches
            # what the raw YAML editor's "load" side already does today.
            if not self.config_path.exists():
                return jsonify({"error": "config.yaml doesn't exist yet."}), 404
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            return send_file(
                # send_file() resolves a relative path against Flask's app
                # root (mediainfo/outputs/), not the process cwd - unlike
                # every other self.config_path use in this file, which are
                # plain Python file I/O and don't have that gotcha.
                self.config_path.resolve(),
                as_attachment=True,
                download_name=f"config-{stamp}.yaml",
                mimetype="application/x-yaml",
            )

        @bp.get("/api/config/backups")
        def list_config_backups():
            backups = list_backups(self.config_path)
            return jsonify(
                {"backups": [{"filename": b.name, "mtime": b.stat().st_mtime} for b in backups]}
            )

        @bp.post("/api/config/backups/restore")
        def restore_config_backup():
            body = request.get_json(silent=True) or {}
            filename = (body.get("filename") or "").strip()
            if not filename:
                return jsonify({"ok": False, "error": "No backup filename given."}), 400
            error, restart_required = self._store.restore_backup(filename)
            if error:
                return jsonify({"ok": False, "error": error}), 400
            if restart_required:
                self._restart_required = True
            response: Dict[str, Any] = {
                "ok": True,
                "restart_required": self._restart_required,
            }
            try:
                Config.load(self.config_path)
            except Exception as exc:
                # Backup was valid when captured, but schema/plugins may have
                # moved on since - warn, don't block: this route exists for
                # disaster recovery, and refusing would leave the user stuck.
                response["warning"] = (
                    f"Restored, but the result fails to load ({exc}) - restore a "
                    "different (e.g. older) backup, or fix config.yaml by hand."
                )
            return jsonify(response)

        @bp.post("/api/restart")
        def restart():
            self._restart_required = False
            threading.Timer(_RESTART_DELAY_SECONDS, _restart_process).start()
            return jsonify({"ok": True})

        @bp.get("/api/hitster-safe")
        def hitster_safe_status():
            enabled = self._hitster_safe_get() if self._hitster_safe_get else False
            return jsonify({"enabled": enabled})

        @bp.post("/api/hitster-safe")
        def hitster_safe_toggle():
            if self._hitster_safe_set is None:
                return jsonify({"error": "Hitster-safe is not available"}), 503
            data = request.get_json(silent=True) or {}
            enabled = bool(data.get("enabled"))
            self._hitster_safe_set(enabled)
            return jsonify({"enabled": enabled})

        @bp.post("/api/appletv/pair/start")
        def appletv_pair_start():
            body = request.get_json(silent=True) or {}
            host = (body.get("host") or "").strip()
            protocol = (body.get("protocol") or "companion").strip().lower()
            if not host:
                return jsonify({"ok": False, "error": "Enter the Apple TV's host/IP first."}), 400
            try:
                result = self._appletv.start(host, protocol)
            except Exception as exc:
                logger.warning("Apple TV pairing start failed: %s", exc)
                return jsonify({"ok": False, "error": str(exc)}), 400
            return jsonify({"ok": True, **result})

        @bp.post("/api/appletv/pair/finish")
        def appletv_pair_finish():
            body = request.get_json(silent=True) or {}
            try:
                result = self._appletv.finish(body.get("pin"))
            except Exception as exc:
                logger.warning("Apple TV pairing finish failed: %s", exc)
                return jsonify({"ok": False, "error": str(exc)}), 400
            return jsonify({"ok": True, **result})

        @bp.post("/api/appletv/pair/cancel")
        def appletv_pair_cancel():
            self._appletv.cancel()
            return jsonify({"ok": True})

        @bp.get("/library")
        def library_page():
            return render_template("config_ui/library.html", url_prefix=url_prefix)

        @bp.get("/api/library/stats")
        def library_stats():
            return jsonify(self._get_library().stats())

        @bp.get("/api/library/search")
        def library_search():
            query = (request.args.get("q") or "").strip()
            if not query:
                return jsonify([])
            results = self._get_library().search(query)
            return jsonify([{"id": artist_id, "name": name} for artist_id, name in results])

        @bp.get("/api/library/artist/<int:artist_id>")
        def library_artist(artist_id: int):
            library = self._get_library()
            name = library.artist_name(artist_id)
            if name is None:
                return jsonify({"error": "Artist not found"}), 404
            albums = library.albums_for_artist(artist_id)
            tracks = library.tracks_for_artist(artist_id)
            return jsonify(
                {
                    "id": artist_id,
                    "name": name,
                    "mbid": library.get_mbid("artist", artist_id),
                    "albums": [{"id": i, "title": t, "mbid": m} for i, t, m in albums],
                    "tracks": [{"id": i, "title": t, "mbid": m} for i, t, m in tracks],
                }
            )

        @bp.get("/overrides")
        def overrides_page():
            return render_template("config_ui/overrides.html", url_prefix=url_prefix)

        @bp.get("/api/overrides")
        def overrides_list():
            if self._overrides is None:
                return jsonify({"enabled": False, "items": []})
            return jsonify({"enabled": True, "items": self._overrides.list()})

        @bp.post("/api/overrides")
        def overrides_add():
            if self._overrides is None:
                return jsonify({"ok": False, "error": "Overrides are disabled"}), 503

            title = (request.form.get("title") or "").strip()
            subtitle = (request.form.get("subtitle") or "").strip()
            file = request.files.get("file")
            if not title:
                return jsonify({"ok": False, "error": "Title is required"}), 400
            if file is None or not file.filename:
                return jsonify({"ok": False, "error": "An image file is required"}), 400

            extension = Path(file.filename).suffix or ".jpg"
            self._overrides.set(title, subtitle, file.read(), extension)
            return jsonify({"ok": True})

        @bp.delete("/api/overrides")
        def overrides_remove():
            if self._overrides is None:
                return jsonify({"ok": False, "error": "Overrides are disabled"}), 503

            body = request.get_json(silent=True) or {}
            removed = self._overrides.remove(
                (body.get("title") or "").strip(), (body.get("subtitle") or "").strip()
            )
            return jsonify({"ok": removed})

        @bp.get("/api/overrides/image/<filename>")
        def overrides_image(filename: str):
            if self._overrides is None:
                return "", 404
            # send_file resolves relative to this safe, fixed directory only
            # - filename never reaches the filesystem as a path (no "..").
            path = self._overrides.dir / Path(filename).name
            if not path.exists():
                return "", 404
            return send_file(path)

        @bp.get("/api/status")
        def status():
            if self._health_fn is None:
                return jsonify({"sources": [], "outputs": [], "enrichers": [], "idle_sources": []})
            data = self._health_fn()
            return jsonify(
                {
                    "sources": data.get("sources", []),
                    "outputs": data.get("outputs", []),
                    "enrichers": data.get("enrichers", []),
                    "idle_sources": data.get("idle_sources", []),
                }
            )

        @bp.post("/api/test/source/<name>")
        def test_source_route(name: str):
            config = Config.load(self.config_path)
            source_config = config.sources.get(name)
            ok, message = test_source(name, source_config)
            return jsonify({"ok": ok, "message": message})

        @bp.post("/api/test/enricher/<name>")
        def test_enricher_route(name: str):
            config = Config.load(self.config_path)
            enricher_config = config.enrichers.get(name)
            ok, message = test_enricher(name, enricher_config)
            return jsonify({"ok": ok, "message": message})

        @bp.post("/api/test/output")
        def test_output_route():
            body = request.get_json(silent=True) or {}
            type_name = body.get("type", "")
            ok, message = test_output(type_name, body)
            return jsonify({"ok": ok, "message": message})

        @bp.post("/api/preview/pixoo")
        def preview_pixoo():
            """Run an uploaded test image through mediainfo.imaging.led_image's
            pipeline using the *currently-edited* form settings (sent as a
            JSON string alongside the file, not read from config.yaml), so
            changing a setting and previewing doesn't require saving first.
            Returns the original/cropped/final/final-upscaled stages as
            base64 PNGs for the pixoo output's detail page (see
            static/config_ui/components.js's renderPixooPreview()) - see
            mediainfo.imaging.led_image.prepare_led_image's docstring for what each
            pipeline stage represents.
            """
            file = request.files.get("file")
            if file is None or not file.filename:
                return jsonify({"ok": False, "error": "An image file is required"}), 400

            try:
                original = flatten_transparency(Image.open(io.BytesIO(file.read())))
            except (UnidentifiedImageError, OSError):
                return jsonify({"ok": False, "error": "Could not read that image"}), 400

            settings = request.form.get("settings")
            opts: Dict[str, Any] = {}
            if settings:
                try:
                    opts = json.loads(settings)
                except ValueError:
                    return jsonify({"ok": False, "error": "Invalid settings"}), 400

            size = int(opts.get("size", 64))
            crop_strategy = opts.get("crop_strategy", "automatic")

            text_cleaned, _decision = maybe_remove_text(
                original,
                target_size=size,
                enabled=bool(opts.get("text_detection_enabled", False)),
                model_path=opts.get("text_detection_model_path", ""),
                remove_small_text=bool(opts.get("remove_small_text", True)),
                preserve_large_logos=bool(opts.get("preserve_large_logos", True)),
                removal_method=opts.get("text_removal_method", "inpaint"),
                max_logo_area_percent=float(opts.get("max_logo_area_percent", 25.0)),
                crop_strategy=crop_strategy,
            )
            cropped = _crop_square(text_cleaned, crop_strategy)
            final = prepare_led_image(
                text_cleaned,
                size=size,
                crop_strategy=crop_strategy,
                palette_size=int(opts.get("palette_size", 24)),
                dithering=opts.get("dithering", "none"),
                contrast_boost=opts.get("contrast_boost", "medium"),
                saturation_boost=opts.get("saturation_boost", "medium"),
                dark_image_boost=bool(opts.get("dark_image_boost", True)),
                pixel_art_mode=bool(opts.get("pixel_art_mode", True)),
            )
            upscaled = final.resize((512, 512), Image.Resampling.NEAREST)

            def _png_b64(image: Image.Image) -> str:
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                return base64.b64encode(buf.getvalue()).decode("ascii")

            return jsonify(
                {
                    "ok": True,
                    "original": _png_b64(original),
                    "cropped": _png_b64(cropped),
                    "final": _png_b64(final),
                    "final_upscaled": _png_b64(upscaled),
                }
            )

        return bp
