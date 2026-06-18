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
"""

from __future__ import annotations

import dataclasses
import io
import logging
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
    Config,
    ConfigUiConfig,
)
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output

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

    def __init__(self, config: ConfigUiConfig, config_path: Path):
        self.config = config
        self.config_path = Path(config_path)
        self._lock = threading.Lock()
        self.app = self._build_app()
        threading.Thread(target=self._run_server, daemon=True).start()

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

    def _build_app(self) -> Flask:
        app = Flask(__name__)

        @app.get("/")
        def index():
            return _INDEX_HTML

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
</style>
</head>
<body>
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
  <span id="status"></span>
</div>

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
  return '<div class="card"><div class="card-title">' + typeName + '</div>'
    + fields.map(function(f) { return renderField(category, typeName, f); }).join('')
    + '</div>';
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
