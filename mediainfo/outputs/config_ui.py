"""Config output: a guided web UI for configuring mediainfo without needing
to know YAML - plus an "Advanced" raw-YAML editor for anything the guided
UI doesn't cover.

The page is a single-page app (templates/config_ui/app.html): one Flask-
rendered shell with a sidebar nav and vanilla-JS client-side routing across
nine sections (Overview, Media sources, Displays & outputs, Artwork &
metadata, Idle screen, Automation & schedules, Library & overrides, System
status, Advanced configuration). library.html and overrides.html remain
their own full pages, linked from the shell's "Library & overrides"
section. There is no build step - just the templates as shipped.

The form is generated from the registered source/output/enricher/idle
config dataclasses (mediainfo.config.SOURCE_CONFIG_TYPES etc.), so any
config type added there automatically gets a card - no UI code to update.
Only scalar fields (bool/int/float/str) are editable in the guided UI; list
fields (transforms, blacklist) are left to the "Advanced" raw-YAML editor,
except flat lists of strings (blacklist, speaker_ips, ...) and the
brightness_schedule/screen_off_hours time-window fields, which get their
own small structured widgets client-side (see _field_widget()).

_build_schema() also carries UI-only presentation metadata alongside each
field - friendly label, help text, "essential vs advanced", "required for
this plugin to work", and (for a few known enum-like fields) a fixed list
of choices - so the client never needs to know Python dataclass internals
to render a sensible form. This is presentation only; _scalar_fields()'s
actual value handling is unchanged from before this metadata existed.

Outputs (the only category that supports multiple instances of the same
type, e.g. two `ulanzi` displays) get "+ Add" / duplicate / remove
controls, and an optional cosmetic `label` field (see
_OutputFilterMixin.label in mediainfo/config/outputs.py) so instances can
be told apart by name instead of just "#1"/"#2". Instances can only be
appended or removed from the end - not reordered or removed from the
middle - so that non-form fields like `transforms` on existing instances
stay attached to the right one; saving always overlays posted fields onto
the *existing* instance at each position rather than replacing it
outright, so transforms etc. on instances you don't touch survive.

Saving always validates the result with Config.from_dict() before writing
anything to disk - both the guided form and the Advanced raw editor go
through this same check, so neither can ever write invalid YAML. The
running process's existing config-file hot-reload (see
mediainfo/__main__.py) picks up the change within a couple of seconds - no
restart needed, EXCEPT for `outputs`, which are only instantiated once at
startup and need a restart to pick up added/removed/reconfigured
instances (see _restart_required below).

Secret fields (api_key, password, token, ...) are never sent to the
browser in cleartext: /api/config blanks their value and reports whether
one is currently set via a separate `secrets_set` map, and the client only
ever POSTs a secret field back if the user actually typed a new value -
see the "Configured / Replace" UI in app.html. Leaving a secret field
untouched in the browser is indistinguishable, on the wire, from never
having included that key at all, and the save path already only overlays
whatever keys are present in the POST body - so an untouched secret is
never overwritten.

`self._restart_required` is set whenever a save touches `outputs` (the
one category that can't hot-reload) or `auth` (every Flask-based output's
HTTP Basic Auth check closes over the AuthConfig instance from process
startup - see install_auth() in _build_app() - so a changed password
doesn't take effect until the process actually restarts), and cleared
when /api/restart is called - it's surfaced via /api/overview so the
Overview page can show a "Restart needed" banner. This is a coarse flag
(any outputs/auth save sets it, even a no-op resubmission) rather than a
real diff - simpler, and errs towards nagging rather than missing a real
restart-required change. If you're locked out and can't reach this page
at all, `python -m mediainfo set-password` (see __main__.py) resets
auth.username/auth.password directly in config.yaml from the command
line - same restart caveat applies.

Known cosmetic limitation: when a brand-new instance is appended to an
output type that already has trailing comments after its last existing
instance (e.g. a comment block introducing the next output type), ruamel.yaml
can render the new instance's YAML *before* that comment instead of after
it - visually confusing, but the data itself is unaffected (it still parses
into the same list, in the same order). Re-saving via the "Advanced" raw
editor lets you tidy up the formatting by hand if it bothers you.

This output has write access to config.yaml, including any credentials in
it, with no authentication of its own - see SECURITY.md before exposing it
beyond a trusted local network.

The page also has a "Restart" button, since changes to `outputs` (added/
removed/reconfigured instances) need a process restart to take effect -
unlike sources/enrichers/idle sources, outputs are only instantiated once
at startup (see mediainfo/__main__.py) and aren't recreated by the config
hot-reload. It works by sending SIGTERM to this process - the same signal
SIGTERM/Ctrl-C/`docker stop` already trigger, so it shuts down via the
existing graceful-shutdown path. Whether it actually comes back up depends
on a process supervisor restarting it: the documented `docker-compose.yml`
(restart: unless-stopped) does this automatically; running the process
directly with no supervisor does not - it'll just exit.

The page can also pair an Apple TV (the same pyatv-based flow as
`python -m mediainfo auth appletv`, see __main__.py), without needing
shell/docker-exec access. Apple TV pairing is async (pyatv) and
inherently a multi-step wizard (start -> enter/confirm PIN -> finish), so
it gets its own short-lived background event loop thread per pairing
attempt, created in `_appletv_pair_start` and torn down in
`_appletv_pair_finish`/`_appletv_pair_cancel`. Only one pairing attempt is
tracked at a time, which is fine for a single-operator local admin tool.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import signal
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template, request, send_file

from mediainfo.artwork_overrides import ArtworkOverrideStore
from mediainfo.cache import ImageCache
from mediainfo.config import (
    ENRICHER_CONFIG_TYPES,
    IDLE_CONFIG_TYPES,
    OUTPUT_CONFIG_TYPES,
    SOURCE_CONFIG_TYPES,
    AuthConfig,
    Config,
    ConfigUiConfig,
)
from mediainfo.config_backup import backup_config_file, list_backups
from mediainfo.models import Artwork, NowPlaying
from mediainfo.musiclibrary import MusicLibrary
from mediainfo.outputs.base import Output
from mediainfo.outputs.config_dashboard import test_enricher, test_output, test_source
from mediainfo.outputs.config_schema import _HIDDEN_TYPE_CATEGORIES, _as_instance_list, _build_schema
from mediainfo.outputs.config_store import ConfigStore
from mediainfo.outputs.config_yaml_io import _dump_config, _read_config
from mediainfo.web_auth import install_auth, is_loopback_address

logger = logging.getLogger(__name__)

# Give the HTTP response time to reach the browser before this process
# receives SIGTERM and starts shutting down.
_RESTART_DELAY_SECONDS = 0.5


def _restart_process() -> None:
    logger.info("Restarting (SIGTERM to self) - requested via the config UI")
    os.kill(os.getpid(), signal.SIGTERM)


@dataclasses.dataclass
class _AppleTvSession:
    """An in-progress pairing attempt, with the resources needed to finish
    or cancel it. The event loop/thread must outlive the request that
    started the pairing, since pyatv's PairingHandler keeps background
    network state tied to the loop it was created on.
    """

    loop: asyncio.AbstractEventLoop
    thread: threading.Thread
    pairing: Any  # pyatv.interface.PairingHandler
    protocol_name: str
    device_name: str
    manual_pin: Optional[int] = None


class ConfigUiOutput(Output):
    handles_images = False

    def __init__(
        self,
        config: ConfigUiConfig,
        config_path: Path,
        auth_config: Optional[AuthConfig] = None,
    ):
        self.config = config
        self.auth_config = auth_config
        self.config_path = Path(config_path)
        self._lock = threading.Lock()
        self._store = ConfigStore(self.config_path, self._lock)
        self._appletv_lock = threading.Lock()
        self._appletv_session: Optional[_AppleTvSession] = None
        self._library: Optional[MusicLibrary] = None
        self._library_db_path: Optional[str] = None
        self._health_fn = None
        self._hitster_safe_get = None
        self._hitster_safe_set = None
        self._overrides: Optional[ArtworkOverrideStore] = None
        # Set whenever a form save touches `outputs` (the one category that
        # needs a restart to take effect, since outputs are only
        # instantiated once at startup) - see the "Restart needed" banner
        # on the Overview page (/api/overview). Cleared when /api/restart
        # is called.
        self._restart_required = False
        self.app = self._build_app()
        threading.Thread(target=self._run_server, daemon=True).start()

    def set_hitster_safe_handlers(self, get_fn, set_fn) -> None:
        """Register the orchestrator's Hitster-safe get/set, so this
        output's button can read and toggle it - see
        Orchestrator.get_hitster_safe."""
        self._hitster_safe_get = get_fn
        self._hitster_safe_set = set_fn

    def set_artwork_overrides(self, store: Optional[ArtworkOverrideStore]) -> None:
        """Register the artwork override store, so the "Overrides" page
        can list/add/remove pins - see wiring.wire_artwork_overrides.
        None means the feature is disabled (overrides.enabled: false)."""
        self._overrides = store

    def set_health_provider(self, fn) -> None:
        """Register a callable that returns the health JSON dict - used by
        the System status section and the Overview page's now-playing/
        active-source summary."""
        self._health_fn = fn

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        pass

    def on_idle(self) -> None:
        pass

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        pass

    def _run_server(self) -> None:
        logger.info("Starting config server on %s:%s", self.config.host, self.config.port)
        self.app.run(host=self.config.host, port=self.config.port, threaded=True)

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
                1 for name in registry
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
        return not is_loopback_address(self.config.host) and self.config.host != "localhost" and not auth_on

    # -- Apple TV pairing ---------------------------------------------

    def _appletv_pair_start(self, host: str, protocol_name: str) -> dict:
        with self._appletv_lock:
            if self._appletv_session is not None:
                raise RuntimeError(
                    "A pairing attempt is already in progress - cancel it first."
                )
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, daemon=True)
            thread.start()

        try:
            result = self._run_appletv_async(
                loop, self._do_appletv_pair_start(loop, host, protocol_name)
            )
        except Exception:
            self._stop_appletv_loop(loop, thread)
            raise

        with self._appletv_lock:
            self._appletv_session = _AppleTvSession(
                loop=loop,
                thread=thread,
                pairing=result["pairing"],
                protocol_name=protocol_name,
                device_name=result["device_name"],
                manual_pin=result["manual_pin"],
            )

        return {
            "device_name": result["device_name"],
            "protocol": protocol_name,
            "device_provides_pin": result["device_provides_pin"],
            "manual_pin": result["manual_pin"],
        }

    @staticmethod
    async def _do_appletv_pair_start(loop, host: str, protocol_name: str) -> dict:
        import pyatv

        protocols = {"companion": pyatv.const.Protocol.Companion, "mrp": pyatv.const.Protocol.MRP}
        protocol = protocols.get(protocol_name)
        if protocol is None:
            raise ValueError(f"Unknown protocol: {protocol_name!r} (expected companion or mrp)")

        results = await pyatv.scan(loop, hosts=[host], timeout=5)
        if not results:
            raise RuntimeError(f"No Apple TV found at {host}")
        conf = results[0]

        pairing = await pyatv.pair(conf, protocol, loop)
        await pairing.begin()

        manual_pin = None
        if not pairing.device_provides_pin:
            manual_pin = 1234
            pairing.pin(manual_pin)

        return {
            "pairing": pairing,
            "device_name": conf.name,
            "device_provides_pin": pairing.device_provides_pin,
            "manual_pin": manual_pin,
        }

    def _appletv_pair_finish(self, pin: Optional[str]) -> dict:
        with self._appletv_lock:
            session = self._appletv_session
        if session is None:
            raise RuntimeError('No pairing in progress - click "Start pairing" first.')

        try:
            credentials = self._run_appletv_async(
                session.loop, self._do_appletv_pair_finish(session, pin)
            )
        finally:
            with self._appletv_lock:
                self._appletv_session = None
            self._stop_appletv_loop(session.loop, session.thread)

        field = f"{session.protocol_name}_credentials"
        self._save_appletv_credentials(field, credentials)
        return {"protocol": session.protocol_name, "field": field, "credentials": credentials}

    @staticmethod
    async def _do_appletv_pair_finish(session: _AppleTvSession, pin: Optional[str]) -> str:
        if session.pairing.device_provides_pin:
            if not pin:
                raise ValueError("Enter the PIN shown on the Apple TV.")
            session.pairing.pin(int(pin))

        await session.pairing.finish()

        if not session.pairing.has_paired:
            await session.pairing.close()
            raise RuntimeError("Pairing failed - check the PIN and try again.")

        credentials = session.pairing.service.credentials
        await session.pairing.close()
        return credentials

    def _appletv_pair_cancel(self) -> None:
        with self._appletv_lock:
            session = self._appletv_session
            self._appletv_session = None
        if session is None:
            return
        try:
            self._run_appletv_async(session.loop, session.pairing.close())
        except Exception:
            logger.exception("Error closing cancelled Apple TV pairing session")
        self._stop_appletv_loop(session.loop, session.thread)

    def _save_appletv_credentials(self, field: str, value: str) -> None:
        with self._lock:
            data = _read_config(self.config_path)
            section = data.setdefault("sources", {})
            entry = section.get("appletv")
            entry = entry if isinstance(entry, dict) else {}
            entry[field] = value
            entry["enabled"] = True
            section["appletv"] = entry

            Config.from_dict(data)

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            backup_config_file(self.config_path)
            with self.config_path.open("w", encoding="utf-8") as f:
                f.write(_dump_config(data))

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
        templates/config_ui/app.html): shown to any non-loopback caller
        when auth is off, because the config form has read+write access to
        config.yaml including all stored credentials.
        """
        if self.auth_config and self.auth_config.enabled:
            return False
        return not is_loopback_address(request.remote_addr)

    def _build_app(self) -> Flask:
        app = Flask(__name__)

        def _shell(initial_section: str):
            return render_template(
                "config_ui/app.html",
                show_auth_warning=self._show_auth_warning(),
                initial_section=initial_section,
            )

        @app.get("/")
        def index():
            return _shell("status" if self.config.ui == "dashboard" else "overview")

        # Both entry points are always reachable on every instance,
        # regardless of `ui` - only the *default* section shown at "/"
        # differs. This lets a dashboard-default instance still reach the
        # editable sections (and vice versa) without running a second
        # output instance. Both render the same single-page shell; only
        # the initially-selected nav section differs.
        @app.get("/form")
        def form_page():
            return _shell("overview")

        @app.get("/dashboard")
        def dashboard_page():
            return _shell("status")

        @app.get("/api/schema")
        def schema():
            return jsonify(_build_schema())

        @app.get("/api/config")
        def get_config():
            with self._lock:
                raw_yaml = (
                    self.config_path.read_text(encoding="utf-8") if self.config_path.exists() else ""
                )
            values, values_secrets = self._store.get_values()
            outputs, output_secrets = self._store.get_output_instances()
            return jsonify({
                "values": values,
                "outputs": outputs,
                "raw_yaml": raw_yaml,
                "secrets_set": {**values_secrets, **output_secrets},
                "hidden_types": self._store.get_hidden_types(),
            })

        @app.get("/api/overview")
        def overview():
            return jsonify(self._compute_overview())

        @app.post("/api/config/form")
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

        @app.post("/api/config/raw")
        def save_raw():
            body = request.get_json(silent=True) or {}
            error, restart_required = self._store.save_raw(body.get("yaml") or "")
            if error:
                return jsonify({"ok": False, "error": error}), 400
            if restart_required:
                self._restart_required = True
            return jsonify({"ok": True, "restart_required": self._restart_required})

        @app.post("/api/config/hidden-types")
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

        @app.get("/api/config/backups")
        def list_config_backups():
            backups = list_backups(self.config_path)
            return jsonify({
                "backups": [{"filename": b.name, "mtime": b.stat().st_mtime} for b in backups]
            })

        @app.post("/api/config/backups/restore")
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
            response: Dict[str, Any] = {"ok": True, "restart_required": self._restart_required}
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

        @app.post("/api/restart")
        def restart():
            self._restart_required = False
            threading.Timer(_RESTART_DELAY_SECONDS, _restart_process).start()
            return jsonify({"ok": True})

        @app.get("/api/hitster-safe")
        def hitster_safe_status():
            enabled = self._hitster_safe_get() if self._hitster_safe_get else False
            return jsonify({"enabled": enabled})

        @app.post("/api/hitster-safe")
        def hitster_safe_toggle():
            if self._hitster_safe_set is None:
                return jsonify({"error": "Hitster-safe is not available"}), 503
            data = request.get_json(silent=True) or {}
            enabled = bool(data.get("enabled"))
            self._hitster_safe_set(enabled)
            return jsonify({"enabled": enabled})

        @app.post("/api/appletv/pair/start")
        def appletv_pair_start():
            body = request.get_json(silent=True) or {}
            host = (body.get("host") or "").strip()
            protocol = (body.get("protocol") or "companion").strip().lower()
            if not host:
                return jsonify({"ok": False, "error": "Enter the Apple TV's host/IP first."}), 400
            try:
                result = self._appletv_pair_start(host, protocol)
            except Exception as exc:
                logger.warning("Apple TV pairing start failed: %s", exc)
                return jsonify({"ok": False, "error": str(exc)}), 400
            return jsonify({"ok": True, **result})

        @app.post("/api/appletv/pair/finish")
        def appletv_pair_finish():
            body = request.get_json(silent=True) or {}
            try:
                result = self._appletv_pair_finish(body.get("pin"))
            except Exception as exc:
                logger.warning("Apple TV pairing finish failed: %s", exc)
                return jsonify({"ok": False, "error": str(exc)}), 400
            return jsonify({"ok": True, **result})

        @app.post("/api/appletv/pair/cancel")
        def appletv_pair_cancel():
            self._appletv_pair_cancel()
            return jsonify({"ok": True})

        @app.get("/library")
        def library_page():
            return render_template("config_ui/library.html")

        @app.get("/api/library/stats")
        def library_stats():
            return jsonify(self._get_library().stats())

        @app.get("/api/library/search")
        def library_search():
            query = (request.args.get("q") or "").strip()
            if not query:
                return jsonify([])
            results = self._get_library().search(query)
            return jsonify([{"id": artist_id, "name": name} for artist_id, name in results])

        @app.get("/api/library/artist/<int:artist_id>")
        def library_artist(artist_id: int):
            library = self._get_library()
            name = library.artist_name(artist_id)
            if name is None:
                return jsonify({"error": "Artist not found"}), 404
            albums = library.albums_for_artist(artist_id)
            tracks = library.tracks_for_artist(artist_id)
            return jsonify({
                "id": artist_id,
                "name": name,
                "mbid": library.get_mbid("artist", artist_id),
                "albums": [{"id": i, "title": t, "mbid": m} for i, t, m in albums],
                "tracks": [{"id": i, "title": t, "mbid": m} for i, t, m in tracks],
            })

        @app.get("/overrides")
        def overrides_page():
            return render_template("config_ui/overrides.html")

        @app.get("/api/overrides")
        def overrides_list():
            if self._overrides is None:
                return jsonify({"enabled": False, "items": []})
            return jsonify({"enabled": True, "items": self._overrides.list()})

        @app.post("/api/overrides")
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

        @app.delete("/api/overrides")
        def overrides_remove():
            if self._overrides is None:
                return jsonify({"ok": False, "error": "Overrides are disabled"}), 503

            body = request.get_json(silent=True) or {}
            removed = self._overrides.remove(
                (body.get("title") or "").strip(), (body.get("subtitle") or "").strip()
            )
            return jsonify({"ok": removed})

        @app.get("/api/overrides/image/<filename>")
        def overrides_image(filename: str):
            if self._overrides is None:
                return "", 404
            # send_file resolves relative to this safe, fixed directory only
            # - filename never reaches the filesystem as a path (no "..").
            path = self._overrides.dir / Path(filename).name
            if not path.exists():
                return "", 404
            return send_file(path)

        @app.get("/api/status")
        def status():
            if self._health_fn is None:
                return jsonify({"sources": [], "outputs": [], "enrichers": [], "idle_sources": []})
            data = self._health_fn()
            return jsonify({
                "sources": data.get("sources", []),
                "outputs": data.get("outputs", []),
                "enrichers": data.get("enrichers", []),
                "idle_sources": data.get("idle_sources", []),
            })

        @app.post("/api/test/source/<name>")
        def test_source_route(name: str):
            config = Config.load(self.config_path)
            source_config = config.sources.get(name)
            ok, message = test_source(name, source_config)
            return jsonify({"ok": ok, "message": message})

        @app.post("/api/test/enricher/<name>")
        def test_enricher_route(name: str):
            config = Config.load(self.config_path)
            enricher_config = config.enrichers.get(name)
            ok, message = test_enricher(name, enricher_config)
            return jsonify({"ok": ok, "message": message})

        @app.post("/api/test/output")
        def test_output_route():
            body = request.get_json(silent=True) or {}
            type_name = body.get("type", "")
            ok, message = test_output(type_name, body)
            return jsonify({"ok": ok, "message": message})

        install_auth(app, self.auth_config)
        return app
