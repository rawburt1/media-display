"""Config output: a web page for editing config.yaml in the browser.

The form is generated from the registered source/output/enricher/idle
config dataclasses (mediainfo.config.SOURCE_CONFIG_TYPES etc.), so any
config type added there automatically gets a form section - no UI code to
update. Only scalar fields (bool/int/str) are editable in the form; list
fields (transforms, blacklist) are left to the "Advanced" raw-YAML editor
at the bottom of the page, which edits the whole file as text.

Outputs (the only category that supports multiple instances of the same
type, e.g. two `ulanzi` displays) get "+ Add instance" / "- Remove last"
controls. Instances can only be appended or removed from the end - not
reordered or removed from the middle - so that non-form fields like
`transforms` on existing instances stay attached to the right one; saving
always overlays posted fields onto the *existing* instance at each
position rather than replacing it outright, so transforms etc. on
instances you don't touch survive.

Saving always validates the result with Config.from_dict() before writing
anything to disk. The running process's existing config-file hot-reload
(see mediainfo/__main__.py) picks up the change within a couple of seconds
- no restart needed.

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
import io
import logging
import os
import signal
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request, send_file
from ruamel.yaml import YAML

from mediainfo.artwork_overrides import ArtworkOverrideStore
from mediainfo.cache import ImageCache
from mediainfo.config import (
    ENRICHER_CONFIG_TYPES,
    IDLE_CONFIG_TYPES,
    OUTPUT_CONFIG_TYPES,
    SOURCE_CONFIG_TYPES,
    AuthConfig,
    CacheConfig,
    Config,
    ConfigUiConfig,
)
from mediainfo.models import Artwork, NowPlaying
from mediainfo.musiclibrary import MusicLibrary
from mediainfo.outputs.base import Output
from mediainfo.outputs.config_dashboard import test_enricher, test_output, test_source
from mediainfo.outputs.config_ui_templates import (
    _DASHBOARD_HTML,
    _INDEX_HTML,
    _LIBRARY_HTML,
    _OVERRIDES_HTML,
)
from mediainfo.web_auth import install_auth

logger = logging.getLogger(__name__)

_SECRET_HINTS = ("password", "token", "secret", "api_key", "key", "credentials", "pin", "npsso")

# Categories where each type has exactly one configured instance.
_SINGLE_INSTANCE_CATEGORIES: Dict[str, Dict[str, type]] = {
    "sources": SOURCE_CONFIG_TYPES,
    "enrichers": ENRICHER_CONFIG_TYPES,
    "idle": IDLE_CONFIG_TYPES,
}

_GENERAL_FIELDS = [
    ("poll_interval_seconds", "int", 5),
    ("rotation_interval_seconds", "int", 30),
]

# Singleton settings sections - like the categories above, but each backed
# by exactly one dataclass (no per-type registry), nested one level under
# their own YAML key (e.g. `cache:`) rather than at the top level like
# `general`'s fields. Keys in the form/values dict look like "cache.dir",
# not "cache.<type_name>.dir".
_FLAT_SECTIONS: Dict[str, type] = {
    "cache": CacheConfig,
}

# List-typed fields simple enough (a flat list of strings) to edit as a
# one-item-per-line text box in the form, rather than the "Advanced" raw
# YAML editor. `transforms` is deliberately excluded - it's a list of
# differently-shaped objects (see config.example.yaml), not a flat list of
# strings, so a generic form field can't represent it usefully.
_SIMPLE_LIST_FIELDS = {"speaker_ips", "blacklist", "device_ips", "ignore_apps", "transition_exclude"}

_yaml = YAML()
_yaml.preserve_quotes = True

# Give the HTTP response time to reach the browser before this process
# receives SIGTERM and starts shutting down.
_RESTART_DELAY_SECONDS = 0.5


def _restart_process() -> None:
    logger.info("Restarting (SIGTERM to self) - requested via the config UI")
    os.kill(os.getpid(), signal.SIGTERM)


def _is_secret(name: str) -> bool:
    lname = name.lower()
    return any(hint in lname for hint in _SECRET_HINTS)


def _scalar_fields(cls: type) -> List[Dict[str, Any]]:
    """Return [{"name", "type", "default", "secret"}] for a config
    dataclass' bool/int/str fields, plus any simple flat-list-of-strings
    field named in _SIMPLE_LIST_FIELDS (type "list", rendered as a
    one-item-per-line text box) - other list-typed fields (e.g.
    `transforms`, a list of differently-shaped objects) are excluded and
    only editable via the page's "Advanced" raw YAML editor.
    """
    fields = []
    for f in dataclasses.fields(cls):
        if f.type == "list" and f.name in _SIMPLE_LIST_FIELDS:
            fields.append({"name": f.name, "type": "list", "default": [], "secret": False})
            continue
        if f.type not in ("bool", "int", "str"):
            continue
        default = f.default if f.default is not dataclasses.MISSING else ""
        fields.append({
            "name": f.name,
            "type": f.type,
            "default": default,
            "secret": _is_secret(f.name),
        })
    return fields


def _build_schema() -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "general": [{"name": n, "type": t, "default": d, "secret": False} for n, t, d in _GENERAL_FIELDS],
    }
    for section, cls in _FLAT_SECTIONS.items():
        schema[section] = _scalar_fields(cls)
    for category, registry in _SINGLE_INSTANCE_CATEGORIES.items():
        schema[category] = {name: _scalar_fields(cls) for name, cls in registry.items()}
    schema["outputs"] = {name: _scalar_fields(cls) for name, cls in OUTPUT_CONFIG_TYPES.items()}
    return schema


def _as_instance_list(raw: Any) -> list:
    """Outputs may be configured in YAML as a single dict or a list of dicts
    (for multiple instances of the same output type) - normalize to a list.
    """
    if isinstance(raw, list):
        return raw
    return [raw] if raw else []


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


def _read_config(path: Path) -> Any:
    if not path.exists():
        return _yaml.map()
    with path.open("r", encoding="utf-8") as f:
        return _yaml.load(f) or _yaml.map()


def _dump_config(data: Any) -> str:
    buf = io.StringIO()
    _yaml.dump(data, buf)
    return buf.getvalue()


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
        self._appletv_lock = threading.Lock()
        self._appletv_session: Optional[_AppleTvSession] = None
        self._library: Optional[MusicLibrary] = None
        self._library_db_path: Optional[str] = None
        self._health_fn = None
        self._hitster_safe_get = None
        self._hitster_safe_set = None
        self._overrides: Optional[ArtworkOverrideStore] = None
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
        the dashboard UI (ui: dashboard) for its status overview."""
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

    def _get_values(self) -> Dict[str, Any]:
        """Flat dotted-key values for the single-instance categories
        (general/sources/enrichers/idle). See _get_output_instances() for
        the (possibly multi-instance) outputs category.
        """
        with self._lock:
            data = _read_config(self.config_path)

        values: Dict[str, Any] = {}
        for name, field_type, default in _GENERAL_FIELDS:
            values[f"general.{name}"] = data.get(name, default)

        for section_name, cls in _FLAT_SECTIONS.items():
            flat_entry = data.get(section_name) or {}
            for field in _scalar_fields(cls):
                values[f"{section_name}.{field['name']}"] = flat_entry.get(
                    field["name"], field["default"]
                )

        for category, registry in _SINGLE_INSTANCE_CATEGORIES.items():
            section = data.get(category) or {}
            for type_name, cls in registry.items():
                entry = section.get(type_name) or {}
                for field in _scalar_fields(cls):
                    values[f"{category}.{type_name}.{field['name']}"] = entry.get(
                        field["name"], field["default"]
                    )
        return values

    def _get_output_instances(self) -> Dict[str, List[Dict[str, Any]]]:
        """Return {output_type: [instance_field_values, ...]} for every
        registered output type, with at least one (possibly all-default)
        instance per type so the form always has something to render.
        """
        with self._lock:
            data = _read_config(self.config_path)

        section = data.get("outputs") or {}
        result: Dict[str, List[Dict[str, Any]]] = {}
        for type_name, cls in OUTPUT_CONFIG_TYPES.items():
            instances = _as_instance_list(section.get(type_name)) or [{}]
            fields = _scalar_fields(cls)
            result[type_name] = [
                {f["name"]: instance.get(f["name"], f["default"]) for f in fields}
                for instance in instances
            ]
        return result

    def _save_form(
        self, values: Dict[str, Any], outputs: Dict[str, List[Dict[str, Any]]]
    ) -> Optional[str]:
        """Merge posted form data into config.yaml. Returns an error message
        on failure, or None on success.
        """
        with self._lock:
            data = _read_config(self.config_path)

            self._merge_single_instance_fields(data, values)

            for type_name, instances in outputs.items():
                if type_name not in OUTPUT_CONFIG_TYPES:
                    continue
                self._merge_output_instances(data, type_name, instances)

            try:
                Config.from_dict(data)
            except Exception as exc:
                logger.warning("Rejected config form save: %s", exc)
                return str(exc)

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with self.config_path.open("w", encoding="utf-8") as f:
                f.write(_dump_config(data))
        return None

    @staticmethod
    def _merge_single_instance_fields(data: Any, values: Dict[str, Any]) -> None:
        """Write posted "general"/flat-section/single-instance (sources,
        enrichers, idle) field values - keys of the form "general.<field>",
        "<flat_section>.<field>" (e.g. "cache.min_width"), or
        "<category>.<type_name>.<field_name>" - into `data` in place.
        """
        for key, value in values.items():
            parts = key.split(".")

            if len(parts) == 2 and parts[0] == "general":
                data[parts[1]] = value
                continue

            if len(parts) == 2 and parts[0] in _FLAT_SECTIONS:
                section = data.setdefault(parts[0], {})
                section[parts[1]] = value
                continue

            if len(parts) != 3:
                continue
            category, type_name, field_name = parts
            if (
                category not in _SINGLE_INSTANCE_CATEGORIES
                or type_name not in _SINGLE_INSTANCE_CATEGORIES[category]
            ):
                continue

            section = data.setdefault(category, {})
            entry = section.get(type_name)
            entry = entry if isinstance(entry, dict) else {}
            entry[field_name] = value
            section[type_name] = entry

    @staticmethod
    def _merge_output_instances(
        data: Any, type_name: str, posted_instances: List[Dict[str, Any]]
    ) -> None:
        """Write `posted_instances` (one dict of field values per instance,
        in order) for `type_name` into `data["outputs"]`.

        Existing instances are mutated in place (preserving non-form fields
        like `transforms` and any YAML comments) rather than replaced, for
        every position present in both the existing and posted lists.
        Posted instances beyond the existing count are brand new (plain
        dicts); existing instances beyond the posted count are dropped -
        i.e. instances can only be appended or removed from the end.
        """
        section = data.setdefault("outputs", {})
        existing_instances = _as_instance_list(section.get(type_name))

        merged = []
        for i, posted in enumerate(posted_instances):
            if i < len(existing_instances):
                instance = existing_instances[i]
                for field_name, value in posted.items():
                    instance[field_name] = value
            else:
                instance = dict(posted)
            merged.append(instance)
        section[type_name] = merged

    def _save_raw(self, raw_yaml: str) -> Optional[str]:
        try:
            parsed = _yaml.load(raw_yaml) or {}
            Config.from_dict(parsed)
        except Exception as exc:
            logger.warning("Rejected raw config save: %s", exc)
            return str(exc)

        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with self.config_path.open("w", encoding="utf-8") as f:
                f.write(raw_yaml)
        return None

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

    def _build_app(self) -> Flask:
        app = Flask(__name__)

        @app.get("/")
        def index():
            return _DASHBOARD_HTML if self.config.ui == "dashboard" else _INDEX_HTML

        # Both views are always reachable on every instance, regardless of
        # `ui` - only the page served at "/" (the instance's default)
        # differs. This lets a dashboard instance reach the full editable
        # form (and vice versa) without running a second output instance.
        @app.get("/form")
        def form_page():
            return _INDEX_HTML

        @app.get("/dashboard")
        def dashboard_page():
            return _DASHBOARD_HTML

        @app.get("/api/schema")
        def schema():
            return jsonify(_build_schema())

        @app.get("/api/config")
        def get_config():
            with self._lock:
                raw_yaml = (
                    self.config_path.read_text(encoding="utf-8") if self.config_path.exists() else ""
                )
            return jsonify({
                "values": self._get_values(),
                "outputs": self._get_output_instances(),
                "raw_yaml": raw_yaml,
            })

        @app.post("/api/config/form")
        def save_form():
            body = request.get_json(silent=True) or {}
            error = self._save_form(body.get("values") or {}, body.get("outputs") or {})
            if error:
                return jsonify({"ok": False, "error": error}), 400
            return jsonify({"ok": True})

        @app.post("/api/config/raw")
        def save_raw():
            body = request.get_json(silent=True) or {}
            error = self._save_raw(body.get("yaml") or "")
            if error:
                return jsonify({"ok": False, "error": error}), 400
            return jsonify({"ok": True})

        @app.post("/api/restart")
        def restart():
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
            return _LIBRARY_HTML

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
            return _OVERRIDES_HTML

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
                return jsonify({"sources": [], "outputs": [], "enrichers": []})
            data = self._health_fn()
            return jsonify({
                "sources": data.get("sources", []),
                "outputs": data.get("outputs", []),
                "enrichers": data.get("enrichers", []),
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


