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

from flask import Flask, jsonify, request
from ruamel.yaml import YAML

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
from mediainfo.models import Artwork, NowPlaying
from mediainfo.musiclibrary import MusicLibrary
from mediainfo.outputs.base import Output
from mediainfo.outputs.config_dashboard import test_enricher, test_output, test_source
from mediainfo.web_auth import install_auth

logger = logging.getLogger(__name__)

_SECRET_HINTS = ("password", "token", "secret", "api_key", "key", "credentials", "pin")

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
    """Return [{"name", "type", "default", "secret"}] for a config dataclass'
    bool/int/str fields (list-typed fields are excluded - see module docstring).
    """
    fields = []
    for f in dataclasses.fields(cls):
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
        self.app = self._build_app()
        threading.Thread(target=self._run_server, daemon=True).start()

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

            for key, value in values.items():
                parts = key.split(".")

                if len(parts) == 2 and parts[0] == "general":
                    data[parts[1]] = value
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


_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mediainfo &middot; configuration</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #080d1a; color: #c0ccdf;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px; min-height: 100vh; padding: 24px 20px 80px;
    max-width: 1080px; margin: 0 auto;
  }
  h1 { font-size: 17px; font-weight: 700; color: #e8f0ff; margin-bottom: 20px; }
  h2 { font-size: 13px; font-weight: 700; letter-spacing: 0.6px; text-transform: uppercase;
       color: #6b7fa8; margin: 26px 0 10px; }
  .card { background: #0d1629; border: 1px solid #1a2540; border-radius: 12px;
          padding: 14px 18px; margin-bottom: 12px; }
  .card-title { font-size: 13px; font-weight: 600; color: #dce8ff; margin-bottom: 8px; }
  .instance { border-top: 1px solid #1a2540; padding-top: 8px; margin-top: 8px; }
  .instance:first-of-type { border-top: none; padding-top: 0; margin-top: 0; }
  .instance-title { font-size: 11px; font-weight: 700; color: #4a5f7a;
                     text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 4px; }
  .instance-actions { display: flex; gap: 8px; margin-top: 10px; }
  .row { display: flex; align-items: center; gap: 10px; padding: 5px 0; }
  .row label { flex: 0 0 200px; font-size: 12px; color: #8aa0c4; }
  .row input[type=text], .row input[type=number], .row input[type=password] {
    flex: 1; background: #080d1a; border: 1px solid #1a2540; border-radius: 6px;
    color: #dce8ff; padding: 6px 9px; font-size: 13px;
  }
  .row input[type=checkbox] { width: 16px; height: 16px; }
  button { background: #2563eb; color: #fff; border: none; border-radius: 8px;
           padding: 9px 18px; font-size: 13px; font-weight: 600; cursor: pointer; }
  button:hover { background: #1d4ed8; }
  button.secondary { background: #1a2540; }
  button.secondary:hover { background: #243456; }
  button.danger { background: #7f1d1d; }
  button.danger:hover { background: #991b1b; }
  button.small { padding: 5px 12px; font-size: 12px; }
  #toolbar { position: sticky; bottom: 0; background: #080d1a; padding: 14px 0;
             border-top: 1px solid #1a2540; display: flex; gap: 10px; align-items: center; }
  #status { font-size: 12px; color: #6b7fa8; }
  #status.ok { color: #22c55e; }
  #status.err { color: #f87171; }
  textarea#raw { width: 100%; min-height: 420px; background: #080d1a; color: #dce8ff;
                 border: 1px solid #1a2540; border-radius: 8px; padding: 12px;
                 font-family: ui-monospace, monospace; font-size: 13px; }
  details summary { cursor: pointer; color: #6b7fa8; font-size: 12px; margin: 30px 0 10px; }
  .nav-link { float: right; color: #6b7fa8; font-size: 12px; text-decoration: none; margin-left: 16px; }
  .nav-link:hover { color: #dce8ff; }
</style>
</head>
<body>
<a class="nav-link" href="/library">Library &rarr;</a>
<a class="nav-link" href="/dashboard">Status &rarr;</a>
<h1>mediainfo configuration</h1>
<div id="form"></div>

<details>
  <summary>Advanced: edit config.yaml as raw text (covers everything, including
    transforms/blacklist lists)</summary>
  <textarea id="raw"></textarea>
  <div id="toolbar">
    <button class="secondary" onclick="saveRaw()">Save raw YAML</button>
    <span id="raw-status"></span>
  </div>
</details>

<div id="toolbar">
  <button onclick="saveForm()">Save</button>
  <button class="danger" onclick="restart()">Restart mediainfo</button>
  <span id="status"></span>
</div>
<p style="font-size: 11px; color: #3b5070; margin-top: 8px;">
  Changes to outputs (added/removed/reconfigured instances) need a restart to take
  effect - sources, enrichers, and idle sources apply automatically within a few
  seconds. Restarting briefly takes every output offline and only comes back up
  automatically if something supervises this process (e.g. Docker's
  <code>restart: unless-stopped</code>, already set up in docker-compose.yml).
</p>

<script>
let schema = null;
let values = null;
let outputsData = null;

function fieldId(category, type, field) { return category + '.' + type + '.' + field; }

function renderField(category, typeName, field) {
  const id = fieldId(category, typeName, field.name);
  const value = values[id] !== undefined ? values[id] : field.default;
  let input;
  if (field.type === 'bool') {
    input = '<input type="checkbox" id="' + id + '" ' + (value ? 'checked' : '') + '>';
  } else {
    const inputType = field.secret ? 'password' : (field.type === 'int' ? 'number' : 'text');
    const v = (value === undefined || value === null) ? '' : String(value).replace(/"/g, '&quot;');
    input = '<input type="' + inputType + '" id="' + id + '" value="' + v + '">';
  }
  return '<div class="row"><label for="' + id + '">' + field.name + '</label>' + input + '</div>';
}

function renderTypeCard(category, typeName, fields) {
  if (!fields.length) return '';
  var extra = (category === 'sources' && typeName === 'appletv') ? renderAppletvPairing() : '';
  return '<div class="card"><div class="card-title">' + typeName + '</div>'
    + fields.map(function(f) { return renderField(category, typeName, f); }).join('')
    + extra
    + '</div>';
}

// -- Apple TV pairing wizard (sources.appletv only) --------------------

var appletvState = {step: 'idle', protocol: 'companion', devicePin: null, error: null};

function renderAppletvPairing() {
  var rows = '';
  if (appletvState.step === 'idle') {
    rows = ''
      + '<select id="appletv-protocol">'
      + '<option value="companion"' + (appletvState.protocol === 'companion' ? ' selected' : '') + '>Companion (tvOS 15+)</option>'
      + '<option value="mrp"' + (appletvState.protocol === 'mrp' ? ' selected' : '') + '>MRP (older devices)</option>'
      + '</select> '
      + '<button type="button" class="secondary small" onclick="appletvPairStart()">Pair</button>';
  } else if (appletvState.step === 'starting') {
    rows = '<span>Scanning and starting pairing&hellip;</span>';
  } else if (appletvState.step === 'need_pin') {
    rows = ''
      + '<div class="row"><label>PIN shown on device</label>'
      + '<input type="text" id="appletv-pin" inputmode="numeric"></div>'
      + '<button type="button" class="secondary small" onclick="appletvPairSubmit()">Submit PIN</button> '
      + '<button type="button" class="secondary small" onclick="appletvPairCancel()">Cancel</button>';
  } else if (appletvState.step === 'need_manual_entry') {
    rows = ''
      + '<p style="font-size:12px;color:#8aa0c4;">Enter <b>' + appletvState.devicePin + '</b> on the '
      + 'Apple TV, then click Continue.</p>'
      + '<button type="button" class="secondary small" onclick="appletvPairSubmit()">Continue</button> '
      + '<button type="button" class="secondary small" onclick="appletvPairCancel()">Cancel</button>';
  } else if (appletvState.step === 'finishing') {
    rows = '<span>Finishing pairing&hellip;</span>';
  } else if (appletvState.step === 'done') {
    rows = '<p style="font-size:12px;color:#22c55e;">Paired - credentials saved below and to config.yaml.</p>'
      + '<button type="button" class="secondary small" onclick="appletvPairReset()">Pair again</button>';
  }
  var error = appletvState.error
    ? '<p style="font-size:12px;color:#f87171;">' + appletvState.error + '</p>'
    : '';
  return '<div class="instance" id="appletv-pairing"><div class="instance-title">Pair</div>' + error + rows + '</div>';
}

function appletvRerenderCard() {
  var fields = schema.sources.appletv;
  var card = document.getElementById('appletv-pairing').closest('.card');
  card.innerHTML = '<div class="card-title">appletv</div>'
    + fields.map(function(f) { return renderField('sources', 'appletv', f); }).join('')
    + renderAppletvPairing();
}

function appletvPairStart() {
  var host = document.getElementById('sources.appletv.host');
  appletvState.protocol = document.getElementById('appletv-protocol').value;
  appletvState.step = 'starting';
  appletvState.error = null;
  appletvRerenderCard();

  fetch('/api/appletv/pair/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({host: host ? host.value : '', protocol: appletvState.protocol}),
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (!d.ok) {
      appletvState.step = 'idle';
      appletvState.error = d.error;
    } else if (d.device_provides_pin) {
      appletvState.step = 'need_pin';
    } else {
      appletvState.step = 'need_manual_entry';
      appletvState.devicePin = d.manual_pin;
    }
    appletvRerenderCard();
  }).catch(function() {
    appletvState.step = 'idle';
    appletvState.error = 'Request failed.';
    appletvRerenderCard();
  });
}

function appletvPairSubmit() {
  var pinEl = document.getElementById('appletv-pin');
  var pin = pinEl ? pinEl.value : null;
  appletvState.step = 'finishing';
  appletvRerenderCard();

  fetch('/api/appletv/pair/finish', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({pin: pin}),
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (!d.ok) {
      appletvState.step = appletvState.devicePin ? 'need_manual_entry' : 'need_pin';
      appletvState.error = d.error;
      appletvRerenderCard();
      return;
    }
    values['sources.appletv.' + d.field] = d.credentials;
    values['sources.appletv.enabled'] = true;
    appletvState.step = 'done';
    appletvRerenderCard();
  }).catch(function() {
    appletvState.error = 'Request failed.';
    appletvRerenderCard();
  });
}

function appletvPairCancel() {
  fetch('/api/appletv/pair/cancel', {method: 'POST'}).catch(function() {});
  appletvState = {step: 'idle', protocol: appletvState.protocol, devicePin: null, error: null};
  appletvRerenderCard();
}

function appletvPairReset() {
  appletvState = {step: 'idle', protocol: appletvState.protocol, devicePin: null, error: null};
  appletvRerenderCard();
}

function renderCategory(title, category) {
  const types = schema[category];
  const cards = Object.keys(types).sort().map(function(t) {
    return renderTypeCard(category, t, types[t]);
  }).join('');
  return '<h2>' + title + '</h2>' + cards;
}

// -- Outputs: the only category that supports multiple instances per type --

function outputFieldId(typeName, index, fieldName) {
  return 'outputs.' + typeName + '.' + index + '.' + fieldName;
}

function renderOutputField(typeName, index, field) {
  const id = outputFieldId(typeName, index, field.name);
  const value = outputsData[typeName][index][field.name];
  const onchange = "updateOutputField('" + typeName + "'," + index + ",'" + field.name + "',this)";
  let input;
  if (field.type === 'bool') {
    input = '<input type="checkbox" id="' + id + '" onchange="' + onchange + '" '
      + (value ? 'checked' : '') + '>';
  } else {
    const inputType = field.secret ? 'password' : (field.type === 'int' ? 'number' : 'text');
    const v = (value === undefined || value === null) ? '' : String(value).replace(/"/g, '&quot;');
    input = '<input type="' + inputType + '" id="' + id + '" onchange="' + onchange + '" value="' + v + '">';
  }
  return '<div class="row"><label for="' + id + '">' + field.name + '</label>' + input + '</div>';
}

function updateOutputField(typeName, index, fieldName, el) {
  const fieldSpec = schema.outputs[typeName].find(function(f) { return f.name === fieldName; });
  outputsData[typeName][index][fieldName] =
    (fieldSpec.type === 'bool') ? el.checked : (fieldSpec.type === 'int' ? Number(el.value || 0) : el.value);
}

function renderOutputTypeCard(typeName, fields) {
  if (!fields.length) return '';
  const instances = outputsData[typeName] || [];
  const instanceHtml = instances.map(function(inst, idx) {
    return '<div class="instance"><div class="instance-title">#' + (idx + 1) + '</div>'
      + fields.map(function(f) { return renderOutputField(typeName, idx, f); }).join('')
      + '</div>';
  }).join('');
  const removeBtn = instances.length
    ? '<button type="button" class="secondary small" onclick="removeInstance(\\'' + typeName + '\\')">- Remove last</button>'
    : '';
  return '<div class="card"><div class="card-title">' + typeName + '</div>'
    + instanceHtml
    + '<div class="instance-actions">'
    + '<button type="button" class="secondary small" onclick="addInstance(\\'' + typeName + '\\')">+ Add instance</button>'
    + removeBtn
    + '</div></div>';
}

function renderOutputsSection() {
  const types = schema.outputs;
  const cards = Object.keys(types).sort().map(function(t) {
    return renderOutputTypeCard(t, types[t]);
  }).join('');
  document.getElementById('outputs-section').innerHTML = cards;
}

function addInstance(typeName) {
  const blank = {};
  schema.outputs[typeName].forEach(function(f) { blank[f.name] = f.default; });
  outputsData[typeName].push(blank);
  renderOutputsSection();
}

function removeInstance(typeName) {
  if (outputsData[typeName].length > 0) outputsData[typeName].pop();
  renderOutputsSection();
}

function render() {
  let html = '<h2>General</h2><div class="card">'
    + schema.general.map(function(f) { return renderField('general', '', f); }).join('')
    + '</div>';
  html += renderCategory('Sources', 'sources');
  html += '<h2>Outputs</h2><div id="outputs-section"></div>';
  html += renderCategory('Enrichers', 'enrichers');
  html += renderCategory('Idle Wallpaper Sources', 'idle');
  document.getElementById('form').innerHTML = html;
  renderOutputsSection();
}

function collectValues() {
  const out = {};
  function collect(category, typeName, fields) {
    fields.forEach(function(f) {
      const id = fieldId(category, typeName, f.name);
      const el = document.getElementById(id);
      if (!el) return;
      out[id] = (f.type === 'bool') ? el.checked : (f.type === 'int' ? Number(el.value || 0) : el.value);
    });
  }
  collect('general', '', schema.general);
  ['sources', 'enrichers', 'idle'].forEach(function(category) {
    Object.keys(schema[category]).forEach(function(t) {
      collect(category, t, schema[category][t]);
    });
  });
  return out;
}

function setStatus(el, ok, message) {
  el.textContent = message;
  el.className = ok ? 'ok' : 'err';
}

function saveForm() {
  const status = document.getElementById('status');
  fetch('/api/config/form', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({values: collectValues(), outputs: outputsData}),
  }).then(function(r) { return r.json(); }).then(function(d) {
    setStatus(status, d.ok, d.ok ? 'Saved - changes take effect within a few seconds.' : d.error);
  }).catch(function() { setStatus(status, false, 'Request failed.'); });
}

function saveRaw() {
  const status = document.getElementById('raw-status');
  fetch('/api/config/raw', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({yaml: document.getElementById('raw').value}),
  }).then(function(r) { return r.json(); }).then(function(d) {
    setStatus(status, d.ok, d.ok ? 'Saved - changes take effect within a few seconds.' : d.error);
    if (d.ok) load();
  }).catch(function() { setStatus(status, false, 'Request failed.'); });
}

function restart() {
  if (!confirm('Restart mediainfo now? Every output goes offline until it comes back up.')) return;
  const status = document.getElementById('status');
  // The process may exit before this resolves, so treat any outcome the same.
  fetch('/api/restart', {method: 'POST'}).catch(function() {});
  setStatus(status, true, 'Restarting...');
}

function load() {
  Promise.all([
    fetch('/api/schema').then(function(r) { return r.json(); }),
    fetch('/api/config').then(function(r) { return r.json(); }),
  ]).then(function(results) {
    schema = results[0];
    values = results[1].values;
    outputsData = results[1].outputs;
    document.getElementById('raw').value = results[1].raw_yaml;
    render();
  });
}

load();
</script>
</body>
</html>
"""

_LIBRARY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mediainfo &middot; library</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #080d1a; color: #c0ccdf;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px; min-height: 100vh; padding: 24px 20px 80px;
    max-width: 1080px; margin: 0 auto;
  }
  h1 { font-size: 17px; font-weight: 700; color: #e8f0ff; margin-bottom: 8px; }
  .nav-link { float: right; color: #6b7fa8; font-size: 12px; text-decoration: none; }
  .nav-link:hover { color: #dce8ff; }
  #stats { font-size: 12px; color: #6b7fa8; margin-bottom: 20px; }
  #search { width: 100%; background: #0d1629; border: 1px solid #1a2540; border-radius: 8px;
            color: #dce8ff; padding: 10px 14px; font-size: 14px; margin-bottom: 16px; }
  .card { background: #0d1629; border: 1px solid #1a2540; border-radius: 12px;
          padding: 14px 18px; margin-bottom: 10px; cursor: pointer; }
  .card:hover { border-color: #2563eb; }
  .card-title { font-size: 13px; font-weight: 600; color: #dce8ff; }
  .card-meta { font-size: 11px; color: #6b7fa8; margin-top: 2px; }
  .detail-list { margin-top: 10px; padding-left: 0; list-style: none; }
  .detail-list li { font-size: 12px; color: #8aa0c4; padding: 4px 0;
                     border-top: 1px solid #1a2540; }
  .detail-list li:first-child { border-top: none; }
  .mbid { color: #4a5f7a; font-family: ui-monospace, monospace; font-size: 10px; }
  .no-mbid { color: #5a3030; }
  h2 { font-size: 12px; font-weight: 700; letter-spacing: 0.4px; text-transform: uppercase;
       color: #6b7fa8; margin: 14px 0 6px; }
  #empty { font-size: 12px; color: #4a5f7a; padding: 20px 0; }
</style>
</head>
<body>
<a class="nav-link" href="/form">&larr; Configuration</a>
<h1>Music library</h1>
<div id="stats">Loading...</div>
<input id="search" type="text" placeholder="Search artists..." autofocus>
<div id="results"></div>

<script>
let debounceTimer = null;

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

function loadStats() {
  fetch('/api/library/stats').then(function(r) { return r.json(); }).then(function(s) {
    document.getElementById('stats').textContent =
      s.artists + ' artist(s), ' + s.albums + ' album(s), ' + s.tracks + ' track(s)';
  });
}

function renderMbid(mbid) {
  return mbid ? '<span class="mbid">' + escapeHtml(mbid) + '</span>'
              : '<span class="no-mbid">no mbid</span>';
}

function showArtist(id) {
  fetch('/api/library/artist/' + id).then(function(r) { return r.json(); }).then(function(a) {
    let html = '<div class="card"><div class="card-title">' + escapeHtml(a.name) + '</div>' +
      '<div class="card-meta">' + renderMbid(a.mbid) + '</div>';
    html += '<h2>Albums (' + a.albums.length + ')</h2><ul class="detail-list">';
    a.albums.forEach(function(album) {
      html += '<li>' + escapeHtml(album.title) + ' &mdash; ' + renderMbid(album.mbid) + '</li>';
    });
    html += '</ul><h2>Tracks (' + a.tracks.length + ')</h2><ul class="detail-list">';
    a.tracks.forEach(function(track) {
      html += '<li>' + escapeHtml(track.title) + ' &mdash; ' + renderMbid(track.mbid) + '</li>';
    });
    html += '</ul></div>';
    document.getElementById('results').innerHTML = html;
  });
}

function renderResults(artists) {
  const results = document.getElementById('results');
  results.innerHTML = '';
  if (artists.length === 0) {
    results.innerHTML = '<div id="empty">No matching artists.</div>';
    return;
  }
  artists.forEach(function(a) {
    const card = document.createElement('div');
    card.className = 'card';
    const title = document.createElement('div');
    title.className = 'card-title';
    title.textContent = a.name;
    card.appendChild(title);
    card.addEventListener('click', function() { showArtist(a.id); });
    results.appendChild(card);
  });
}

document.getElementById('search').addEventListener('input', function(e) {
  const query = e.target.value.trim();
  clearTimeout(debounceTimer);
  if (!query) {
    document.getElementById('results').innerHTML = '';
    return;
  }
  debounceTimer = setTimeout(function() {
    fetch('/api/library/search?q=' + encodeURIComponent(query))
      .then(function(r) { return r.json(); })
      .then(renderResults);
  }, 200);
});

loadStats();
</script>
</body>
</html>
"""

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mediainfo &middot; status</title>
<style>
  :root {
    --bg: #080d1a; --card: #0d1629; --border: #1a2540; --text: #c0ccdf; --bright: #e8f0ff;
    --muted: #6b7fa8; --muted2: #4a5f7a; --accent: #2563eb; --accent-hover: #1d4ed8;
    --chip-bg: #0d1629; --mono-bg: #050810;
  }
  html[data-theme="light"] {
    --bg: #f3f5fa; --card: #ffffff; --border: #dde3ee; --text: #2a3550; --bright: #0f172a;
    --muted: #5b6a85; --muted2: #6b7fa8; --accent: #2563eb; --accent-hover: #1d4ed8;
    --chip-bg: #eef1f8; --mono-bg: #0f172a;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px; min-height: 100vh; padding: 24px 20px 60px;
    max-width: 1200px; margin: 0 auto;
  }
  .hdr { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; }
  h1 { font-size: 17px; font-weight: 700; color: var(--bright); }
  .nav-link { color: var(--muted); font-size: 12px; text-decoration: none; }
  .nav-link:hover { color: var(--bright); }
  #theme-toggle { margin-left: auto; background: var(--chip-bg); border: 1px solid var(--border);
                  color: var(--text); border-radius: 8px; padding: 6px 12px; font-size: 12px;
                  cursor: pointer; }
  #theme-toggle:hover { border-color: var(--accent); }
  .filters { display: flex; gap: 8px; margin-bottom: 22px; flex-wrap: wrap; }
  .chip { background: var(--chip-bg); border: 1px solid var(--border); color: var(--muted);
          border-radius: 999px; padding: 6px 14px; font-size: 12px; font-weight: 600;
          cursor: pointer; user-select: none; }
  .chip:hover { border-color: var(--accent); }
  .chip.active { background: var(--accent); border-color: var(--accent); color: #fff; }
  h2 { font-size: 12px; font-weight: 700; letter-spacing: 0.6px; text-transform: uppercase;
       color: var(--muted); margin: 26px 0 10px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
          padding: 14px 16px; }
  .card-top { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .card-name { font-size: 13px; font-weight: 600; color: var(--bright); flex: 1;
               white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .badge { font-size: 10px; font-weight: 700; letter-spacing: 0.3px; text-transform: uppercase;
           padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
  .b-active, .b-ok { background: #052012; color: #22c55e; }
  .b-idle { background: #051a2e; color: #60a5fa; }
  .b-disabled { background: #1c1505; color: #f59e0b; }
  .b-not_configured { background: #15171f; color: #8a93a6; }
  .b-error { background: #1c0808; color: #f87171; }
  .card-detail { font-size: 11px; color: var(--muted2); font-family: ui-monospace, monospace;
                 margin-bottom: 10px; min-height: 14px; }
  .card-actions { display: flex; align-items: center; gap: 8px; }
  button.test-btn { background: var(--accent); color: #fff; border: none; border-radius: 7px;
                     padding: 6px 12px; font-size: 12px; font-weight: 600; cursor: pointer; }
  button.test-btn:hover { background: var(--accent-hover); }
  button.test-btn:disabled { opacity: 0.6; cursor: default; }
  .test-result { font-size: 11px; font-family: ui-monospace, monospace; margin-top: 8px;
                 padding: 8px 10px; border-radius: 6px; background: var(--mono-bg);
                 color: #9fb3cc; white-space: pre-wrap; word-break: break-word; display: none; }
  .test-result.show { display: block; }
  .test-result.ok { color: #4ade80; }
  .test-result.fail { color: #f87171; }
  button.test-btn.secondary { background: var(--chip-bg); color: var(--text);
                               border: 1px solid var(--border); }
  button.test-btn.secondary:hover { border-color: var(--accent); }
  .edit-form { margin-bottom: 10px; }
  .edit-row { display: flex; align-items: center; justify-content: space-between;
              gap: 8px; margin-bottom: 6px; }
  .edit-row label { font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace;
                     white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .edit-row input[type="text"], .edit-row input[type="password"], .edit-row input[type="number"] {
    flex: 1; max-width: 150px; background: var(--card); border: 1px solid var(--border);
    border-radius: 6px; color: var(--bright); padding: 4px 8px; font-size: 12px;
  }
  #empty { font-size: 12px; color: var(--muted2); padding: 10px 0; }
</style>
</head>
<body>
<div class="hdr">
  <h1>mediainfo status</h1>
  <a class="nav-link" href="/form">&larr; Configuration</a>
  <button id="theme-toggle" onclick="toggleTheme()">&#9728; / &#9790;</button>
</div>

<div class="filters" id="filters">
  <div class="chip active" data-filter="all">All</div>
  <div class="chip" data-filter="active">Active</div>
  <div class="chip" data-filter="idle">Idle</div>
  <div class="chip" data-filter="enabled">Enabled</div>
  <div class="chip" data-filter="disabled">Disabled</div>
  <div class="chip" data-filter="error">Error</div>
</div>

<h2>Sources</h2>
<div class="grid" id="sources-grid"></div>

<h2>Outputs</h2>
<div class="grid" id="outputs-grid"></div>

<h2>Enrichers</h2>
<div class="grid" id="enrichers-grid"></div>

<script>
let statusData = { sources: [], outputs: [], enrichers: [] };
let currentFilter = 'all';
let testResults = {};  // kind + ':' + id -> {ok, message} - survives the 10s auto-refresh

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('mediainfo-theme', theme);
}
function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  applyTheme(current === 'light' ? 'dark' : 'light');
}
applyTheme(localStorage.getItem('mediainfo-theme') || 'dark');

function badgeClass(status) { return 'badge b-' + (status || 'not_configured'); }

function matchesFilter(status) {
  if (currentFilter === 'all') return true;
  if (currentFilter === 'enabled') return status !== 'disabled' && status !== 'not_configured';
  return status === currentFilter;
}

const _DETAIL_OMIT = ['name', 'type', 'status', 'last_error', 'last_error_ago_seconds', 'instance_index'];

function detailText(item) {
  return Object.keys(item)
    .filter(function(k) { return _DETAIL_OMIT.indexOf(k) === -1 && item[k] !== null && item[k] !== '' && item[k] !== undefined; })
    .map(function(k) { return k + ': ' + item[k]; })
    .join(' \xb7 ');
}

function itemId(item) { return item.name || item.type; }

function renderGrid(containerId, items, kind) {
  const el = document.getElementById(containerId);
  const visible = items.filter(function(it) { return matchesFilter(it.status); });
  if (visible.length === 0) {
    el.innerHTML = '<div id="empty">No items match this filter.</div>';
    return;
  }
  el.innerHTML = '';
  visible.forEach(function(item) {
    const card = document.createElement('div');
    card.className = 'card';

    const top = document.createElement('div');
    top.className = 'card-top';
    const name = document.createElement('div');
    name.className = 'card-name';
    name.textContent = item.name || item.type;
    const badge = document.createElement('span');
    badge.className = badgeClass(item.status);
    badge.textContent = item.status;
    top.appendChild(name);
    top.appendChild(badge);
    card.appendChild(top);

    const detail = document.createElement('div');
    detail.className = 'card-detail';
    detail.textContent = detailText(item) || ' ';
    card.appendChild(detail);

    if (item.last_error) {
      const autoError = document.createElement('div');
      autoError.className = 'test-result show fail';
      autoError.textContent = '⚠ ' + item.last_error;
      card.appendChild(autoError);
    }

    const actions = document.createElement('div');
    actions.className = 'card-actions';
    const btn = document.createElement('button');
    btn.className = 'test-btn';
    btn.textContent = 'Test connection';
    const editBtn = document.createElement('button');
    editBtn.className = 'test-btn secondary';
    editBtn.textContent = 'Edit';
    const result = document.createElement('div');
    result.className = 'test-result';
    const key = kind + ':' + itemId(item);
    const prior = testResults[key];
    if (prior) {
      result.classList.add('show', prior.ok ? 'ok' : 'fail');
      result.textContent = prior.message;
    }
    btn.addEventListener('click', function() { runTest(kind, item, btn, result); });
    editBtn.addEventListener('click', function() { startEdit(kind, item, card); });
    actions.appendChild(btn);
    actions.appendChild(editBtn);
    card.appendChild(actions);
    card.appendChild(result);

    el.appendChild(card);
  });
}

function runTest(kind, item, btn, resultEl) {
  const key = kind + ':' + itemId(item);
  btn.disabled = true;
  btn.textContent = 'Testing...';
  resultEl.className = 'test-result show';
  resultEl.textContent = 'Running...';

  let request;
  if (kind === 'source') {
    request = fetch('/api/test/source/' + encodeURIComponent(item.name), { method: 'POST' });
  } else if (kind === 'enricher') {
    request = fetch('/api/test/enricher/' + encodeURIComponent(item.name), { method: 'POST' });
  } else {
    request = fetch('/api/test/output', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(item),
    });
  }

  request
    .then(function(r) { return r.json(); })
    .then(function(d) {
      testResults[key] = d;
      resultEl.classList.add(d.ok ? 'ok' : 'fail');
      resultEl.textContent = d.message;
    })
    .catch(function() {
      const failed = { ok: false, message: 'Request failed.' };
      testResults[key] = failed;
      resultEl.classList.add('fail');
      resultEl.textContent = failed.message;
    })
    .finally(function() {
      btn.disabled = false;
      btn.textContent = 'Test connection';
    });
}

let schemaPromise = null;
function loadSchema() {
  if (!schemaPromise) schemaPromise = fetch('/api/schema').then(function(r) { return r.json(); });
  return schemaPromise;
}

function categoryFor(kind) {
  return kind === 'source' ? 'sources' : (kind === 'enricher' ? 'enrichers' : 'outputs');
}

function fieldInputHtml(id, field, value) {
  if (field.type === 'bool') {
    return '<input type="checkbox" id="' + id + '"' + (value ? ' checked' : '') + '>';
  }
  const inputType = field.secret ? 'password' : (field.type === 'int' ? 'number' : 'text');
  const v = (value === undefined || value === null) ? '' : String(value).replace(/"/g, '&quot;');
  return '<input type="' + inputType + '" id="' + id + '" value="' + v + '">';
}

function startEdit(kind, item, card) {
  const category = categoryFor(kind);
  const typeName = item.name || item.type;

  Promise.all([loadSchema(), fetch('/api/config').then(function(r) { return r.json(); })])
    .then(function(results) {
      const schemaData = results[0];
      const config = results[1];
      const fields = (category === 'outputs') ? schemaData.outputs[typeName] : schemaData[category][typeName];
      let currentValues = {};
      if (category === 'outputs') {
        const idx = item.instance_index || 0;
        const instances = config.outputs[typeName] || [{}];
        currentValues = instances[idx] || {};
      } else {
        fields.forEach(function(f) {
          currentValues[f.name] = config.values[category + '.' + typeName + '.' + f.name];
        });
      }
      renderEditCard(kind, item, card, fields, currentValues);
    });
}

function renderEditCard(kind, item, card, fields, currentValues) {
  card.innerHTML = '';

  const top = document.createElement('div');
  top.className = 'card-top';
  const name = document.createElement('div');
  name.className = 'card-name';
  name.textContent = item.name || item.type;
  top.appendChild(name);
  card.appendChild(top);

  const formEl = document.createElement('div');
  formEl.className = 'edit-form';
  fields.forEach(function(f) {
    const row = document.createElement('div');
    row.className = 'edit-row';
    const label = document.createElement('label');
    label.textContent = f.name;
    label.setAttribute('for', 'edit-' + f.name);
    row.appendChild(label);
    const wrapper = document.createElement('div');
    wrapper.innerHTML = fieldInputHtml('edit-' + f.name, f, currentValues[f.name]);
    row.appendChild(wrapper.firstChild);
    formEl.appendChild(row);
  });
  card.appendChild(formEl);

  const resultEl = document.createElement('div');
  resultEl.className = 'test-result';

  const actions = document.createElement('div');
  actions.className = 'card-actions';
  const saveBtn = document.createElement('button');
  saveBtn.className = 'test-btn';
  saveBtn.textContent = 'Save';
  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'test-btn secondary';
  cancelBtn.textContent = 'Cancel';
  cancelBtn.addEventListener('click', function() { render(); });
  saveBtn.addEventListener('click', function() { saveEdit(kind, item, fields, saveBtn, resultEl); });
  actions.appendChild(saveBtn);
  actions.appendChild(cancelBtn);
  card.appendChild(actions);
  card.appendChild(resultEl);
}

function saveEdit(kind, item, fields, btn, resultEl) {
  const category = categoryFor(kind);
  const typeName = item.name || item.type;
  const edited = {};
  fields.forEach(function(f) {
    const el = document.getElementById('edit-' + f.name);
    edited[f.name] = (f.type === 'bool') ? el.checked : (f.type === 'int' ? Number(el.value || 0) : el.value);
  });

  btn.disabled = true;
  btn.textContent = 'Saving...';
  resultEl.className = 'test-result show';
  resultEl.textContent = 'Saving...';

  let request;
  if (category === 'outputs') {
    const idx = item.instance_index || 0;
    request = fetch('/api/config').then(function(r) { return r.json(); }).then(function(config) {
      const instances = (config.outputs[typeName] || [{}]).slice();
      instances[idx] = edited;
      const outputsBody = {};
      outputsBody[typeName] = instances;
      return fetch('/api/config/form', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outputs: outputsBody }),
      });
    });
  } else {
    const values = {};
    Object.keys(edited).forEach(function(k) { values[category + '.' + typeName + '.' + k] = edited[k]; });
    request = fetch('/api/config/form', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values: values }),
    });
  }

  request
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.ok) {
        resultEl.classList.add('ok');
        resultEl.textContent = 'Saved.';
        load();
      } else {
        resultEl.classList.add('fail');
        resultEl.textContent = d.error || 'Save failed.';
        btn.disabled = false;
        btn.textContent = 'Save';
      }
    })
    .catch(function() {
      resultEl.classList.add('fail');
      resultEl.textContent = 'Request failed.';
      btn.disabled = false;
      btn.textContent = 'Save';
    });
}

function render() {
  document.querySelectorAll('.chip').forEach(function(chip) {
    chip.classList.toggle('active', chip.dataset.filter === currentFilter);
  });
  renderGrid('sources-grid', statusData.sources, 'source');
  renderGrid('outputs-grid', statusData.outputs, 'output');
  renderGrid('enrichers-grid', statusData.enrichers, 'enricher');
}

document.getElementById('filters').addEventListener('click', function(e) {
  const chip = e.target.closest('.chip');
  if (!chip) return;
  currentFilter = chip.dataset.filter;
  render();
});

function load() {
  fetch('/api/status')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      statusData = d;
      render();
    });
}

load();
setInterval(load, 10000);
</script>
</body>
</html>
"""
