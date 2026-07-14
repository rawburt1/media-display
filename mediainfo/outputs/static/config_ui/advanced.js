'use strict';

// Advanced section (finishes the two-shell migration from ADR 0001/H5) -
// settings cards for the three flat "advanced"-category components
// (general/auth/logging, already fully editable via components.js's
// #component/<id> detail page, just not reachable from any nav before
// this), plus the config-file management tools that have no per-component
// home: backups list/restore, download/upload, and the raw YAML editor
// for anything the guided pages don't cover. Ported from the classic
// shell's renderAdvanced()/renderBackupsList()/saveRawYaml() et al.
// Loaded after dashboard.js/components.js - shares their esc()/apiFetch()/
// API_PREFIX/CSRF_HEADERS/componentsData/componentsById/fetchComponents()/
// fetchDashboard().

var ADVANCED_COMPONENT_IDS = ['general', 'auth', 'logging'];

var rawYaml = null;              // null = not yet loaded
var configBackups = null;        // null = not yet loaded
var backupRestoreResult = null;  // {text, className} - persists across re-renders, same pattern as detailPendingStatus
var advancedRawStatus = null;    // {text, className} - see components.js's detailPendingStatus for why this exists

function fetchRawYaml() {
  return apiFetch('/api/config').then(function(r) { return r.json(); }).then(function(cfg) {
    rawYaml = cfg.raw_yaml || '';
  }).catch(function() { rawYaml = ''; });
}

function advancedSettingsCards() {
  var items = ADVANCED_COMPONENT_IDS.map(function(id) { return componentsById[id]; }).filter(Boolean);
  if (!items.length) return '<span class="field-help">Nothing here yet.</span>';
  return '<div class="component-list">' + items.map(componentCard).join('') + '</div>';
}

// Refreshes only the settings cards from a 15s poll tick (dashboard.js's
// fetchComponents()) - a full renderAdvancedSection() would blow away
// whatever the user is mid-typing in the raw YAML textarea below, the same
// reasoning as renderLibrarySettingsCards().
function renderAdvancedSettingsCards() {
  var el = document.getElementById('advanced-settings-cards');
  if (el) el.innerHTML = advancedSettingsCards();
}

function renderAdvancedSection() {
  var el = document.getElementById('section-advanced');
  if (!componentsData || rawYaml === null) {
    el.innerHTML = '<h1>Advanced</h1><p class="lede">Loading…</p>';
    if (rawYaml === null) {
      fetchRawYaml().then(function() { if (currentSection === 'advanced') renderAdvancedSection(); });
    }
    if (configBackups === null) fetchConfigBackups();
    return;
  }

  var html = '<h1>Advanced</h1><p class="lede">Security, logging, and general timing settings, plus config file backups and a raw YAML editor covering anything not yet in the guided pages.</p>';

  html += '<h2 class="group-title">Settings</h2>'
    + '<p class="field-help" style="margin:-4px 0 8px;">Changes to Authentication need a restart to take effect - the login check only runs once, at startup. Locked out and can’t reach this page at all? Reset the password from the command line: <code>python -m mediainfo set-password --config config.yaml</code>.</p>'
    + '<div id="advanced-settings-cards">' + advancedSettingsCards() + '</div>';

  html += '<h2 class="group-title">Backups</h2>'
    + '<p class="field-help" style="margin:-4px 0 8px;">A backup of config.yaml is taken automatically before every save (from here, <code>set-password</code>, or Apple TV pairing) - the 10 most recent are kept. Restoring backs up the current config.yaml first too, so a restore can itself be undone.</p>'
    + '<div class="card">' + renderBackupsList() + '</div>';

  html += '<h2 class="group-title">Config file</h2>'
    + '<p class="field-help" style="margin:-4px 0 8px;">Download the current config.yaml (e.g. to keep outside the automatic backups above, or move to another machine) - includes credentials, same as this page itself. Uploading loads a file into the raw YAML editor below to review before saving; it does not save automatically.</p>'
    + '<div class="card"><div class="action-row">'
    + '<a class="btn secondary" href="' + API_PREFIX + '/api/config/download">Download config.yaml</a>'
    + '<button type="button" class="btn secondary" onclick="document.getElementById(\'config-upload-input\').click()">Upload config.yaml…</button>'
    + '<input type="file" id="config-upload-input" accept=".yaml,.yml,text/yaml" style="display:none" onchange="loadConfigFileIntoRawEditor(this)">'
    + '</div></div>';

  html += '<h2 class="group-title">Raw YAML editor</h2>'
    + '<div class="card">'
    + '<textarea id="raw-yaml" aria-label="Raw YAML configuration" style="width:100%;min-height:280px;font-family:monospace;">' + esc(rawYaml) + '</textarea>'
    + '<div class="action-row">'
    + '<button type="button" class="btn" onclick="saveRawYaml()">Save raw YAML</button>'
    + '<span id="raw-status" role="status" aria-live="polite"></span>'
    + '</div></div>';

  el.innerHTML = html;

  if (advancedRawStatus) {
    var statusEl = document.getElementById('raw-status');
    if (statusEl) { statusEl.textContent = advancedRawStatus.text; statusEl.className = advancedRawStatus.className; }
    advancedRawStatus = null;
  }
}

function renderBackupsList() {
  if (configBackups === null) return '<p class="field-help">Loading…</p>';
  if (!configBackups.length) {
    return '<p class="field-help">No backups yet - one will be created automatically before the next save.</p>';
  }
  var rows = configBackups.map(function(b) {
    var when = new Date(b.mtime * 1000).toLocaleString();
    return '<div class="row" style="display:flex;align-items:center;justify-content:space-between;gap:10px;">'
      + '<span>' + esc(when) + ' <span class="field-help" style="margin:0;">(' + esc(b.filename) + ')</span></span>'
      + '<button type="button" class="btn secondary small" onclick="restoreConfigBackup(\'' + esc(b.filename) + '\')">Restore</button>'
      + '</div>';
  }).join('');
  var prior = backupRestoreResult;
  return rows
    + '<div class="action-row">'
    + '<span id="backups-status" class="' + (prior ? prior.className : '') + '" role="status" aria-live="polite">' + (prior ? esc(prior.text) : '') + '</span>'
    + '</div>';
}

function fetchConfigBackups() {
  return apiFetch('/api/config/backups').then(function(r) { return r.json(); }).then(function(d) {
    configBackups = d.backups || [];
    if (currentSection === 'advanced') renderAdvancedSection();
  }).catch(function() { configBackups = []; });
}

function refreshAfterConfigWrite() {
  configBackups = null;
  rawYaml = null;
  return Promise.all([fetchRawYaml(), fetchConfigBackups(), fetchComponents(), fetchDashboard()]).then(function() {
    if (currentSection === 'advanced') renderAdvancedSection();
  });
}

function restoreConfigBackup(filename) {
  if (!confirm('Restore config.yaml from this backup? The current config.yaml is itself backed up '
    + 'first, so this can be undone the same way. Some changes may need a restart to take effect.')) return;
  var statusEl = document.getElementById('backups-status');
  statusEl.textContent = 'Restoring…'; statusEl.className = '';
  apiFetch('/api/config/backups/restore', {
    method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, CSRF_HEADERS),
    body: JSON.stringify({ filename: filename }),
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (!d.ok) {
      backupRestoreResult = { text: d.error, className: 'err' };
      renderAdvancedSection();
      return;
    }
    backupRestoreResult = d.warning
      ? { text: d.warning, className: 'err' }
      : {
          text: d.restart_required ? 'Restored - a restart is needed for this to fully take effect.' : 'Restored.',
          className: 'ok',
        };
    refreshAfterConfigWrite();
  }).catch(function() {
    backupRestoreResult = { text: 'Request failed.', className: 'err' };
    renderAdvancedSection();
  });
}

function loadConfigFileIntoRawEditor(inputEl) {
  var file = inputEl.files && inputEl.files[0];
  inputEl.value = ''; // allow re-selecting the same file later
  if (!file) return;
  var textarea = document.getElementById('raw-yaml');
  if (textarea.value !== rawYaml && !confirm('Replace the raw YAML editor’s content with this file? Unsaved edits there will be lost.')) {
    return;
  }
  var reader = new FileReader();
  reader.onload = function() {
    textarea.value = String(reader.result || '');
    var statusEl = document.getElementById('raw-status');
    statusEl.textContent = 'Loaded ' + file.name + ' - review, then click “Save raw YAML” to apply it.';
    statusEl.className = '';
  };
  reader.onerror = function() {
    var statusEl = document.getElementById('raw-status');
    statusEl.textContent = 'Could not read ' + file.name + '.';
    statusEl.className = 'err';
  };
  reader.readAsText(file);
}

function saveRawYaml() {
  var statusEl = document.getElementById('raw-status');
  var text = document.getElementById('raw-yaml').value;
  statusEl.textContent = 'Saving…'; statusEl.className = '';
  apiFetch('/api/config/raw', {
    method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, CSRF_HEADERS),
    body: JSON.stringify({ yaml: text }),
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (!d.ok) {
      statusEl.textContent = d.error || 'Save failed.';
      statusEl.className = 'err';
      return;
    }
    advancedRawStatus = {
      text: 'Saved - most changes take effect within a few seconds (outputs and authentication need a restart).',
      className: 'ok',
    };
    refreshAfterConfigWrite();
  }).catch(function() { statusEl.textContent = 'Request failed.'; statusEl.className = 'err'; });
}
