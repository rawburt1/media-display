"""HTML/CSS/JS templates for the config output's pages: the editable
config form (_INDEX_HTML), the read-only library browser (_LIBRARY_HTML),
and the status dashboard (_DASHBOARD_HTML).

Split out from config_ui.py - these are returned verbatim by its Flask
routes with no per-instance interpolation, so they're pure static assets
that happen to be Python string literals rather than files; keeping them
separate from ConfigUiOutput's actual route/business logic keeps that
file from growing without bound every time a button gets added to a page.
"""

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
  #hitster-safe-btn.active { background: #7c3aed; }
  #hitster-safe-btn.active:hover { background: #6d28d9; }
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
  .auth-warning { background: #431407; border: 1px solid #9a3412; border-radius: 8px;
                  padding: 10px 14px; margin-bottom: 16px; font-size: 13px; color: #fed7aa; }
  .auth-warning strong { color: #fb923c; }
  .auth-warning a { color: #fb923c; }
</style>
</head>
<body>
<a class="nav-link" href="/library">Library &rarr;</a>
<a class="nav-link" href="/overrides">Overrides &rarr;</a>
<a class="nav-link" href="/dashboard">Status &rarr;</a>
<h1>mediainfo configuration</h1>
<!-- __AUTH_WARNING__ -->
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
  <button class="secondary" id="hitster-safe-btn" onclick="toggleHitsterSafe()">Hitster-safe</button>
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

function fieldId(category, type, field) {
  // `type` is '' for flat single-instance sections (general, cache) -
  // omit it rather than leaving a double dot, which the server's
  // "<category>.<field>" parser (for those flat sections) doesn't match,
  // so edits would silently fail to save.
  return type ? (category + '.' + type + '.' + field) : (category + '.' + field);
}

// Simple flat-list-of-strings fields (speaker_ips, blacklist, device_ips,
// ignore_apps, transition_exclude) round-trip through a one-item-per-line
// textarea: list -> text for display, text -> list when read back.
function listToTextarea(value) {
  return Array.isArray(value) ? value.join('\\n') : '';
}
function textareaToList(text) {
  return text.split('\\n').map(function(s) { return s.trim(); }).filter(function(s) { return s; });
}

function renderField(category, typeName, field) {
  const id = fieldId(category, typeName, field.name);
  const value = values[id] !== undefined ? values[id] : field.default;
  let input;
  if (field.type === 'bool') {
    input = '<input type="checkbox" id="' + id + '" ' + (value ? 'checked' : '') + '>';
  } else if (field.type === 'list') {
    input = '<textarea id="' + id + '" rows="3" placeholder="One per line">'
      + listToTextarea(value).replace(/</g, '&lt;') + '</textarea>';
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
  } else if (field.type === 'list') {
    input = '<textarea id="' + id + '" onchange="' + onchange + '" rows="3" placeholder="One per line">'
      + listToTextarea(value).replace(/</g, '&lt;') + '</textarea>';
  } else {
    const inputType = field.secret ? 'password' : (field.type === 'int' ? 'number' : 'text');
    const v = (value === undefined || value === null) ? '' : String(value).replace(/"/g, '&quot;');
    input = '<input type="' + inputType + '" id="' + id + '" onchange="' + onchange + '" value="' + v + '">';
  }
  return '<div class="row"><label for="' + id + '">' + field.name + '</label>' + input + '</div>';
}

function updateOutputField(typeName, index, fieldName, el) {
  const fieldSpec = schema.outputs[typeName].find(function(f) { return f.name === fieldName; });
  outputsData[typeName][index][fieldName] = (fieldSpec.type === 'bool') ? el.checked
    : (fieldSpec.type === 'int') ? Number(el.value || 0)
    : (fieldSpec.type === 'list') ? textareaToList(el.value)
    : el.value;
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
  html += '<h2>Cache</h2><div class="card">'
    + schema.cache.map(function(f) { return renderField('cache', '', f); }).join('')
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
      out[id] = (f.type === 'bool') ? el.checked
        : (f.type === 'int') ? Number(el.value || 0)
        : (f.type === 'list') ? textareaToList(el.value)
        : el.value;
    });
  }
  collect('general', '', schema.general);
  collect('cache', '', schema.cache);
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

let hitsterSafeEnabled = false;

function renderHitsterSafeButton() {
  const btn = document.getElementById('hitster-safe-btn');
  btn.textContent = hitsterSafeEnabled ? 'Hitster-safe: ON' : 'Hitster-safe';
  btn.classList.toggle('active', hitsterSafeEnabled);
}

function toggleHitsterSafe() {
  fetch('/api/hitster-safe', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({enabled: !hitsterSafeEnabled}),
  })
    .then(function(r) { return r.json(); })
    .then(function(d) { hitsterSafeEnabled = !!d.enabled; renderHitsterSafeButton(); })
    .catch(function() {});
}

fetch('/api/hitster-safe')
  .then(function(r) { return r.json(); })
  .then(function(d) { hitsterSafeEnabled = !!d.enabled; renderHitsterSafeButton(); })
  .catch(function() {});

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

_OVERRIDES_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mediainfo &middot; overrides</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #080d1a; color: #c0ccdf;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px; min-height: 100vh; padding: 24px 20px 80px;
    max-width: 720px; margin: 0 auto;
  }
  h1 { font-size: 17px; font-weight: 700; color: #e8f0ff; margin-bottom: 8px; }
  .nav-link { float: right; color: #6b7fa8; font-size: 12px; text-decoration: none; }
  .nav-link:hover { color: #dce8ff; }
  p.hint { font-size: 12px; color: #6b7fa8; margin-bottom: 20px; }
  #disabled { font-size: 13px; color: #8a6d3b; background: #2a2210; border: 1px solid #4a3a18;
              border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; }
  form#add-form { background: #0d1629; border: 1px solid #1a2540; border-radius: 12px;
                   padding: 16px 18px; margin-bottom: 20px; }
  form#add-form label { display: block; font-size: 12px; color: #6b7fa8; margin: 10px 0 4px; }
  form#add-form input[type=text] {
    width: 100%; background: #080d1a; border: 1px solid #1a2540; border-radius: 6px;
    color: #dce8ff; padding: 8px 10px; font-size: 13px;
  }
  form#add-form input[type=file] { margin-top: 4px; font-size: 12px; color: #8aa0c4; }
  form#add-form button {
    margin-top: 14px; background: #2563eb; color: #fff; border: none; border-radius: 6px;
    padding: 9px 16px; font-size: 13px; font-weight: 600; cursor: pointer;
  }
  form#add-form button:hover { background: #1d4ed8; }
  #message { font-size: 12px; margin-top: 10px; }
  #message.error { color: #f87171; }
  #message.success { color: #4ade80; }
  .card { background: #0d1629; border: 1px solid #1a2540; border-radius: 12px;
          padding: 12px 14px; margin-bottom: 10px; display: flex; align-items: center; gap: 12px; }
  .card img { width: 56px; height: 56px; object-fit: cover; border-radius: 6px; background: #080d1a; }
  .card-info { flex: 1; min-width: 0; }
  .card-title { font-size: 13px; font-weight: 600; color: #dce8ff; }
  .card-subtitle { font-size: 11px; color: #6b7fa8; margin-top: 2px; }
  .card button {
    background: transparent; color: #f87171; border: 1px solid #3a1f1f; border-radius: 6px;
    padding: 6px 10px; font-size: 12px; cursor: pointer;
  }
  .card button:hover { background: #2a1414; }
  #empty { font-size: 12px; color: #4a5f7a; padding: 12px 0; }
</style>
</head>
<body>
<a class="nav-link" href="/form">&larr; Configuration</a>
<h1>Artwork overrides</h1>
<p class="hint">
  Pin a specific image for a title/subtitle that never gets a good poster
  from any enricher - matched by exact title + subtitle (e.g. movie title,
  or song title + artist), case-insensitive.
</p>
<div id="disabled" style="display:none">
  Overrides are disabled (set <code>overrides.enabled: true</code> in config.yaml).
</div>
<form id="add-form" enctype="multipart/form-data">
  <label for="title">Title</label>
  <input id="title" name="title" type="text" required>
  <label for="subtitle">Subtitle (artist, episode label, etc. - leave blank if not applicable)</label>
  <input id="subtitle" name="subtitle" type="text">
  <label for="file">Image file</label>
  <input id="file" name="file" type="file" accept="image/*" required>
  <button type="submit">Save override</button>
  <div id="message"></div>
</form>
<div id="list"></div>

<script>
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

function showMessage(text, isError) {
  const el = document.getElementById('message');
  el.textContent = text;
  el.className = isError ? 'error' : 'success';
}

function renderList(items) {
  const list = document.getElementById('list');
  if (items.length === 0) {
    list.innerHTML = '<div id="empty">No overrides yet.</div>';
    return;
  }
  list.innerHTML = '';
  items.forEach(function(item) {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML =
      '<img src="/api/overrides/image/' + encodeURIComponent(item.filename) + '" alt="">' +
      '<div class="card-info">' +
        '<div class="card-title">' + escapeHtml(item.title) + '</div>' +
        '<div class="card-subtitle">' + escapeHtml(item.subtitle || '(no subtitle)') + '</div>' +
      '</div>';
    const button = document.createElement('button');
    button.textContent = 'Remove';
    button.addEventListener('click', function() { removeOverride(item.title, item.subtitle); });
    card.appendChild(button);
    list.appendChild(card);
  });
}

function loadList() {
  fetch('/api/overrides').then(function(r) { return r.json(); }).then(function(data) {
    if (data.enabled === false) {
      document.getElementById('disabled').style.display = 'block';
      document.getElementById('add-form').style.display = 'none';
    }
    renderList(data.items || []);
  });
}

function removeOverride(title, subtitle) {
  fetch('/api/overrides', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: title, subtitle: subtitle }),
  }).then(function(r) { return r.json(); }).then(function() { loadList(); });
}

document.getElementById('add-form').addEventListener('submit', function(e) {
  e.preventDefault();
  const formData = new FormData(e.target);
  fetch('/api/overrides', { method: 'POST', body: formData })
    .then(function(r) { return r.json().then(function(data) { return [r.ok, data]; }); })
    .then(function(result) {
      const ok = result[0], data = result[1];
      if (ok) {
        showMessage('Saved.', false);
        e.target.reset();
        loadList();
      } else {
        showMessage(data.error || 'Failed to save override.', true);
      }
    });
});

loadList();
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
  button.danger { background: #dc2626; color: #fff; border: none; border-radius: 8px;
                  padding: 6px 12px; font-size: 12px; font-weight: 600; cursor: pointer; }
  button.danger:hover { background: #b91c1c; }
  #restart-status { font-size: 12px; color: var(--muted); }
  #hitster-safe-btn { background: var(--chip-bg); border: 1px solid var(--border);
                       color: var(--text); border-radius: 8px; padding: 6px 12px;
                       font-size: 12px; font-weight: 600; cursor: pointer; }
  #hitster-safe-btn:hover { border-color: var(--accent); }
  #hitster-safe-btn.active { background: #7c3aed; border-color: #7c3aed; color: #fff; }
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
  .b-error, .b-unavailable { background: #1c0808; color: #f87171; }
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
  <button class="danger" onclick="restartDashboard()">Restart mediainfo</button>
  <span id="restart-status"></span>
  <button id="hitster-safe-btn" onclick="toggleHitsterSafe()">Hitster-safe</button>
  <button id="theme-toggle" onclick="toggleTheme()">&#9728; / &#9790;</button>
</div>

<div class="filters" id="filters">
  <div class="chip active" data-filter="all">All</div>
  <div class="chip" data-filter="active">Active</div>
  <div class="chip" data-filter="idle">Idle</div>
  <div class="chip" data-filter="enabled">Enabled</div>
  <div class="chip" data-filter="disabled">Disabled</div>
  <div class="chip" data-filter="unavailable">Unavailable</div>
</div>

<h2>Sources</h2>
<div class="grid" id="sources-grid"></div>

<h2>Outputs</h2>
<div class="grid" id="outputs-grid"></div>

<h2>Enrichers</h2>
<div class="grid" id="enrichers-grid"></div>

<script>
// Simple flat-list-of-strings fields (speaker_ips, blacklist, device_ips,
// ignore_apps, transition_exclude) round-trip through a one-item-per-line
// textarea: list -> text for display, text -> list when read back.
function listToTextarea(value) {
  return Array.isArray(value) ? value.join('\\n') : '';
}
function textareaToList(text) {
  return text.split('\\n').map(function(s) { return s.trim(); }).filter(function(s) { return s; });
}

let statusData = { sources: [], outputs: [], enrichers: [] };
let currentFilter = 'all';
let testResults = {};  // kind + ':' + id -> {ok, message} - survives the 10s auto-refresh
let statusOverrides = {};  // 'source:' + name -> 'unavailable', set when a manual test fails
// kind + ':' + id -> the open edit card's DOM element, kept across the 10s
// auto-refresh so a card mid-edit isn't blown away (and any text already
// typed into it lost) the moment a refresh happens to land while it's open.
let editingCards = {};

function restartDashboard() {
  if (!confirm('Restart mediainfo now? Every output goes offline until it comes back up.')) return;
  const statusEl = document.getElementById('restart-status');
  fetch('/api/restart', { method: 'POST' }).catch(function() {});
  statusEl.textContent = 'Restarting...';
}

let hitsterSafeEnabled = false;

function renderHitsterSafeButton() {
  const btn = document.getElementById('hitster-safe-btn');
  btn.textContent = hitsterSafeEnabled ? 'Hitster-safe: ON' : 'Hitster-safe';
  btn.classList.toggle('active', hitsterSafeEnabled);
}

function toggleHitsterSafe() {
  fetch('/api/hitster-safe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled: !hitsterSafeEnabled }),
  })
    .then(function(r) { return r.json(); })
    .then(function(d) { hitsterSafeEnabled = !!d.enabled; renderHitsterSafeButton(); })
    .catch(function() {});
}

fetch('/api/hitster-safe')
  .then(function(r) { return r.json(); })
  .then(function(d) { hitsterSafeEnabled = !!d.enabled; renderHitsterSafeButton(); })
  .catch(function() {});

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

// "error" (automatic - the orchestrator's own polling backed off after a
// failed connection) and "unavailable" (manual - a "Test connection" click
// failed) are deliberately separate internally - see the "Add restart
// button and unavailable status..." commit - but both just mean "this
// isn't working" to someone reading the dashboard, so they're shown and
// filtered identically.
function statusLabel(status) { return status === 'error' ? 'unavailable' : status; }

function matchesFilter(status) {
  if (currentFilter === 'all') return true;
  if (currentFilter === 'enabled') return status !== 'disabled' && status !== 'not_configured';
  if (currentFilter === 'unavailable') return status === 'error' || status === 'unavailable';
  return status === currentFilter;
}

// Raw config fields (host, port, ip, dir, api_key, max_search_candidates,
// ...) are deliberately not shown here - the dashboard is a status
// overview, not a config dump (that's what /form is for), and a blocklist
// of config field names is a losing game across every source/output/
// enricher's own config dataclass. Only this fixed set of *computed*
// (non-config) fields is ever worth showing on a card.
const _DETAIL_ALLOW = ['wallpapers_loaded', 'videos_loaded'];

function detailText(item) {
  return Object.keys(item)
    .filter(function(k) { return _DETAIL_ALLOW.indexOf(k) !== -1 && item[k] !== null && item[k] !== '' && item[k] !== undefined; })
    .map(function(k) { return k.replace(/_/g, ' ') + ': ' + item[k]; })
    .join(' \xb7 ');
}

function itemId(item) { return item.name || item.type; }

function effectiveStatus(kind, item) {
  const key = kind + ':' + itemId(item);
  return statusOverrides[key] || item.status;
}

function renderGrid(containerId, items, kind) {
  const el = document.getElementById(containerId);
  const visible = items.filter(function(it) { return matchesFilter(effectiveStatus(kind, it)); });
  if (visible.length === 0) {
    el.innerHTML = '<div id="empty">No items match this filter.</div>';
    return;
  }
  el.innerHTML = '';
  visible.forEach(function(item) {
    const editKey = kind + ':' + itemId(item);
    if (editingCards[editKey]) {
      // Re-mount the same element rather than rebuilding it, so an
      // in-progress edit (and anything already typed into it) survives
      // this refresh untouched.
      el.appendChild(editingCards[editKey]);
      return;
    }

    const status = effectiveStatus(kind, item);
    const card = document.createElement('div');
    card.className = 'card';

    const top = document.createElement('div');
    top.className = 'card-top';
    const name = document.createElement('div');
    name.className = 'card-name';
    name.textContent = item.name || item.type;
    const badge = document.createElement('span');
    badge.className = badgeClass(status);
    badge.textContent = statusLabel(status);
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
      if (kind === 'source') {
        if (d.ok) delete statusOverrides[key]; else statusOverrides[key] = 'unavailable';
        render();
        return;
      }
      resultEl.classList.add(d.ok ? 'ok' : 'fail');
      resultEl.textContent = d.message;
    })
    .catch(function() {
      const failed = { ok: false, message: 'Request failed.' };
      testResults[key] = failed;
      if (kind === 'source') {
        statusOverrides[key] = 'unavailable';
        render();
        return;
      }
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
  if (field.type === 'list') {
    return '<textarea id="' + id + '" rows="3" placeholder="One per line">'
      + listToTextarea(value).replace(/</g, '&lt;') + '</textarea>';
  }
  const inputType = field.secret ? 'password' : (field.type === 'int' ? 'number' : 'text');
  const v = (value === undefined || value === null) ? '' : String(value).replace(/"/g, '&quot;');
  return '<input type="' + inputType + '" id="' + id + '" value="' + v + '">';
}

function startEdit(kind, item, card) {
  const category = categoryFor(kind);
  const typeName = item.name || item.type;
  // Registered immediately (not after the fetch below resolves) so a
  // refresh landing while the schema/config request is still in flight
  // re-mounts this same card instead of replacing it out from under it.
  editingCards[kind + ':' + itemId(item)] = card;

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
  cancelBtn.addEventListener('click', function() {
    delete editingCards[kind + ':' + itemId(item)];
    render();
  });
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
    edited[f.name] = (f.type === 'bool') ? el.checked
      : (f.type === 'int') ? Number(el.value || 0)
      : (f.type === 'list') ? textareaToList(el.value)
      : el.value;
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
        delete editingCards[kind + ':' + itemId(item)];
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

function pruneStatusOverrides(data) {
  (data.sources || []).forEach(function(item) {
    const key = 'source:' + itemId(item);
    if (statusOverrides[key] && item.status !== 'idle') {
      delete statusOverrides[key];
    }
  });
}

function load() {
  fetch('/api/status')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      statusData = d;
      pruneStatusOverrides(d);
      render();
    });
}

load();
setInterval(load, 10000);
</script>
</body>
</html>
"""
