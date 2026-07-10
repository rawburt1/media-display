'use strict';

// Media/Metadata/Appearance/Displays category lists + the per-component
// detail page (Fas 4 of the GUI redesign). Loaded after dashboard.js and
// reuses its esc()/STATUS_LABELS/CATEGORY_TO_SECTION/SECTION_TITLES/
// componentsData/componentsById/hasUnsavedComponentEdits - no module
// system, just script-tag order (same pattern as the rest of this shell).
//
// Category lists are read-only browsing (built from the already-fetched
// /api/ui/components, same data Pipeline uses). The detail page is the one
// place in the new shell that writes config - it always goes through the
// exact same endpoints the classic shell (app.html) already uses:
// /api/config/form (save), /api/test/{source,enricher}/<name> and
// /api/test/output (test connection). No new backend endpoint exists or
// is needed for this.

// ---------------------------------------------------------------------
// Category lists
// ---------------------------------------------------------------------
var CATEGORY_FOR_SECTION = { media: 'media', metadata: 'metadata', appearance: 'appearance', displays: 'display' };
var CATEGORY_GROUPS = {
  media: [
    { type: 'source', label: 'Sources' },
    { type: 'idle_source', label: 'Idle screen' },
  ],
  metadata: [
    { type: 'enricher', label: 'Enrichers' },
    { type: 'text_enricher', label: 'Lyrics & text' },
  ],
  appearance: [
    { type: 'theme', label: 'Themes' },
  ],
  displays: [
    { type: 'output', label: 'Displays' },
  ],
};

// Deterministic hue from a component id, used only for the Appearance
// (theme) cards' decorative accent strip below - not a real preview of
// what the theme looks like (that would require actually rendering it,
// out of scope here), just a way to tell theme cards apart at a glance.
function hueForId(id) {
  var h = 0;
  for (var i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) % 360;
  return h;
}

function componentCard(c) {
  var readOnly = c.component_type === 'text_enricher';
  var badge = readOnly
    ? '<span class="badge b-unknown">View only</span>'
    : '<span class="badge b-' + esc(c.status) + '">' + esc(STATUS_LABELS[c.status] || c.status) + '</span>';
  var warning = c.warnings && c.warnings.length ? '<div class="warning">' + esc(c.warnings[0]) + '</div>' : '';
  var accent = '';
  var cardClass = 'component-card';
  if (c.component_type === 'theme') {
    var hue = hueForId(c.id);
    cardClass += ' component-card--theme';
    accent = '<div class="component-card-accent" style="background:linear-gradient(135deg, hsl(' + hue + ',70%,55%), hsl(' + ((hue + 45) % 360) + ',70%,55%));"></div>';
  }
  return '<a class="' + cardClass + '" href="#component/' + esc(c.id) + '">' + accent
    + '<div class="body"><div class="name">' + esc(c.name) + '</div>' + badge
    + (c.description ? '<div class="desc">' + esc(c.description) + '</div>' : '')
    + warning
    + '</div></a>';
}

function renderCategorySection(name) {
  var el = document.getElementById('section-' + name);
  if (!componentsData) {
    el.innerHTML = '<h1>' + esc(SECTION_TITLES[name]) + '</h1><p class="lede">Loading…</p>';
    return;
  }
  var category = CATEGORY_FOR_SECTION[name];
  var groups = CATEGORY_GROUPS[name];
  var html = '<h1>' + esc(SECTION_TITLES[name]) + '</h1><p class="lede">Click a component to view or edit its settings.</p>';
  var any = false;
  groups.forEach(function(group) {
    var items = componentsData.filter(function(c) { return c.category === category && c.component_type === group.type; });
    if (!items.length) return;
    any = true;
    if (groups.length > 1) html += '<h2 class="group-title">' + esc(group.label) + '</h2>';
    html += '<div class="component-list">' + items.map(componentCard).join('') + '</div>';
  });
  if (!any) html += '<div class="card"><span class="field-help">Nothing here yet.</span></div>';
  el.innerHTML = html;
}

// ---------------------------------------------------------------------
// Component detail page - local edit state
// ---------------------------------------------------------------------
var detailComponent = null;          // last-fetched UiComponent for the current detail page
var detailEdits = {};                // non-output/theme: fieldName -> new value
var detailReplacingSecret = {};      // fieldName -> true while its "Replace" input is open
var detailOutputsWorking = null;     // output/theme: full instance array (deep copy) for the owning output type
var detailOutputType = null;         // output type name detailOutputsWorking belongs to
var detailThemeName = null;          // set only for component_type "theme"
var detailAdvancedOpen = false;
// A save's confirmation ("Saved - changes take effect...") is set on the
// *current* #detail-save-status element, but the save handler immediately
// triggers a refetch to show fresh server state (flips secret badges
// etc.) - that refetch's own render replaces the whole section, including
// a brand new (empty) #detail-save-status, wiping the message out before
// anyone can read it. Stashing it here and having
// renderComponentDetailBody() apply it once after that fresh render lands
// avoids the race instead of racing the DOM directly.
var detailPendingStatus = null;

function classicHrefFor(c) {
  if (c.component_type === 'text_enricher') return '/form#advanced';
  if (c.component_type === 'idle_source') return '/form#idle';
  if (c.component_type === 'source') return '/form#sources';
  if (c.component_type === 'enricher') return '/form#artwork';
  if (c.component_type === 'theme' || c.component_type === 'output') return '/form#outputs';
  return '/form';
}

function findDetailField(name) {
  var all = (detailComponent.essential_fields || []).concat(detailComponent.advanced_fields || []);
  for (var i = 0; i < all.length; i++) {
    if (all[i].name === name) return all[i];
  }
  return { name: name };
}

function getFieldValue(field) {
  if (detailComponent.component_type === 'output') {
    return detailOutputsWorking[0] ? detailOutputsWorking[0][field.name] : field.value;
  }
  if (detailComponent.component_type === 'theme') {
    return detailOutputsWorking[0].themes[detailThemeName][field.name];
  }
  return Object.prototype.hasOwnProperty.call(detailEdits, field.name) ? detailEdits[field.name] : field.value;
}

function setFieldValue(field, value) {
  hasUnsavedComponentEdits = true;
  if (detailComponent.component_type === 'output') {
    detailOutputsWorking[0][field.name] = value;
  } else if (detailComponent.component_type === 'theme') {
    detailOutputsWorking[0].themes[detailThemeName][field.name] = value;
  } else {
    detailEdits[field.name] = value;
  }
}

function onDetailFieldChange(name, value) {
  setFieldValue(findDetailField(name), value);
  renderComponentDetailBody();
}
function onDetailSecretInput(name, value) {
  // Deliberately no re-render here (mirrors app.html's rawInput) - a full
  // re-render on every keystroke would rebuild this very input out from
  // under the user's cursor after the first character.
  setFieldValue(findDetailField(name), value);
}
function onDetailSecretReplace(name) {
  detailReplacingSecret[name] = true;
  renderComponentDetailBody();
}
function onDetailSecretCancel(name) {
  delete detailReplacingSecret[name];
  renderComponentDetailBody();
}

function renderSecretField(field, value) {
  var isSet = !!field.secret_set;
  if (detailReplacingSecret[field.name]) {
    return '<div class="secret-box">'
      + '<input type="password" autocomplete="new-password" placeholder="Enter new value" value="' + esc(value || '') + '" '
      + 'oninput="onDetailSecretInput(\'' + esc(field.name) + '\', this.value)">'
      + '<button type="button" class="btn secondary small" onclick="onDetailSecretCancel(\'' + esc(field.name) + '\')">Cancel</button>'
      + '</div>';
  }
  return '<div class="secret-box">'
    + '<span class="secret-badge ' + (isSet ? 'set' : 'unset') + '">' + (isSet ? 'Configured' : 'Not set') + '</span>'
    + '<button type="button" class="btn secondary small" onclick="onDetailSecretReplace(\'' + esc(field.name) + '\')">Replace' + (isSet ? '…' : '') + '</button>'
    + (isSet ? '<button type="button" class="btn secondary small" onclick="onDetailFieldChange(\'' + esc(field.name) + '\', \'\')">Clear</button>' : '')
    + '</div>';
}

function fieldValueDisplay(field, value) {
  if (field.secret) return field.secret_set ? '••••••••' : '(not set)';
  if (Array.isArray(value)) return value.length ? value.join(', ') : '(none)';
  return value == null || value === '' ? '(not set)' : String(value);
}

function renderStaticField(field, value) {
  return '<div class="field"><div class="field-row">'
    + '<label class="field-label">' + esc(field.label) + '</label>'
    + '<div class="field-control"><div class="readonly-field">' + esc(fieldValueDisplay(field, value)) + '</div>'
    + (field.help ? '<div class="field-help">' + esc(field.help) + '</div>' : '')
    + '</div></div></div>';
}

function renderUnsupportedWidgetField(field, value) {
  return '<div class="field"><div class="field-row">'
    + '<label class="field-label">' + esc(field.label) + '</label>'
    + '<div class="field-control"><div class="readonly-field">' + esc(fieldValueDisplay(field, value)) + '</div>'
    + '<div class="field-help">This field type isn’t editable here yet - '
    + '<a href="' + esc(classicHrefFor(detailComponent)) + '">edit in Advanced settings</a>.</div>'
    + '</div></div></div>';
}

function renderDetailField(field) {
  var value = getFieldValue(field);

  if (detailComponent.component_type === 'text_enricher') {
    return renderStaticField(field, value);
  }

  var control;
  if (field.secret) {
    control = renderSecretField(field, value);
  } else if (field.type === 'bool') {
    control = '<input type="checkbox" ' + (value ? 'checked' : '')
      + ' onchange="onDetailFieldChange(\'' + esc(field.name) + '\', this.checked)">';
  } else if (field.choices) {
    control = '<select onchange="onDetailFieldChange(\'' + esc(field.name) + '\', this.value)">'
      + field.choices.map(function(ch) {
        return '<option value="' + esc(ch) + '"' + (ch === value ? ' selected' : '') + '>' + esc(ch) + '</option>';
      }).join('') + '</select>';
  } else if (field.widget === 'time_range' || field.widget === 'brightness_schedule' || field.type === 'list') {
    return renderUnsupportedWidgetField(field, value);
  } else {
    var inputType = (field.type === 'int' || field.type === 'float') ? 'number' : 'text';
    var onchange = inputType === 'number'
      ? "onDetailFieldChange('" + esc(field.name) + "', Number(this.value || 0))"
      : "onDetailFieldChange('" + esc(field.name) + "', this.value)";
    control = '<input type="' + inputType + '" value="' + esc(value == null ? '' : value) + '" onchange="' + onchange + '">';
  }

  var reqMark = field.required ? '<span class="req">*</span>' : '';
  return '<div class="field"><div class="field-row">'
    + '<label class="field-label">' + esc(field.label) + reqMark + '</label>'
    + '<div class="field-control">' + control
    + (field.help ? '<div class="field-help">' + esc(field.help) + '</div>' : '')
    + '</div></div></div>';
}

function renderComponentDetailBody() {
  var el = document.getElementById('section-component');
  var c = detailComponent;
  var sectionName = CATEGORY_TO_SECTION[c.category] || 'dashboard';
  var readOnly = c.component_type === 'text_enricher';

  var html = '<a class="back-link" href="#' + esc(sectionName) + '">← Back to ' + esc(SECTION_TITLES[sectionName] || 'list') + '</a>';
  html += '<h1>' + esc(c.name) + '</h1>';
  if (c.description) html += '<p class="lede">' + esc(c.description) + '</p>';
  html += '<span class="badge b-' + esc(c.status) + '">' + esc(STATUS_LABELS[c.status] || c.status) + '</span>';

  if (c.warnings && c.warnings.length) {
    html += '<ul class="warning-list" style="margin-top:12px;">'
      + c.warnings.map(function(w) { return '<li class="warning-item">' + esc(w) + '</li>'; }).join('')
      + '</ul>';
  }

  if (readOnly) {
    html += '<div class="card" style="margin-top:14px;"><span class="field-help">'
      + 'This component is view-only in the new dashboard for now - '
      + '<a href="' + esc(classicHrefFor(c)) + '">edit it via Advanced → raw YAML</a>.</span></div>';
  }

  html += '<div class="card" style="margin-top:14px;">';
  html += (c.essential_fields || []).map(renderDetailField).join('');
  if (c.advanced_fields && c.advanced_fields.length) {
    html += '<details class="advanced-toggle"' + (detailAdvancedOpen ? ' open' : '') + ' ontoggle="detailAdvancedOpen = this.open">'
      + '<summary>Advanced settings</summary>'
      + c.advanced_fields.map(renderDetailField).join('')
      + '</details>';
  }
  html += '</div>';

  if (!readOnly) {
    html += '<div class="action-row">';
    if (c.supports_test) {
      html += '<button type="button" class="btn secondary" id="detail-test-btn" onclick="runDetailTest()">Test connection</button>';
    }
    html += '<button type="button" class="btn secondary" onclick="discardDetailEdits()">Discard</button>';
    html += '<button type="button" class="btn" onclick="saveDetailComponent()">Save</button>';
    html += '</div>';
    html += '<div class="test-result" id="detail-test-result"></div>';
    html += '<div id="detail-save-status" style="margin-top:8px;font-size:12.5px;"></div>';
  }

  el.innerHTML = html;

  if (detailPendingStatus) {
    var statusEl = document.getElementById('detail-save-status');
    if (statusEl) {
      statusEl.textContent = detailPendingStatus.text;
      statusEl.className = detailPendingStatus.className;
    }
    detailPendingStatus = null;
  }
}

function loadOutputInstances(c) {
  var typeName = c.config_path.split('.')[1];
  return fetch('/api/config').then(function(r) { return r.json(); }).then(function(cfg) {
    var instances = (cfg.outputs && cfg.outputs[typeName]) || [];
    detailOutputType = typeName;
    detailOutputsWorking = JSON.parse(JSON.stringify(instances));
    if (!detailOutputsWorking.length) detailOutputsWorking.push({});
  });
}

function loadThemeInstances(c) {
  var themeName = c.config_path.split('.')[1];
  return fetch('/api/config').then(function(r) { return r.json(); }).then(function(cfg) {
    var instances = (cfg.outputs && cfg.outputs.themes) || [];
    detailOutputType = 'themes';
    detailThemeName = themeName;
    detailOutputsWorking = JSON.parse(JSON.stringify(instances));
    if (!detailOutputsWorking.length) detailOutputsWorking.push({});
    if (!detailOutputsWorking[0].themes) detailOutputsWorking[0].themes = {};
    if (!detailOutputsWorking[0].themes[themeName]) detailOutputsWorking[0].themes[themeName] = {};
  });
}

function fetchComponentDetail(id) {
  var el = document.getElementById('section-component');
  fetch('/api/ui/component/' + encodeURIComponent(id)).then(function(r) { return r.json(); }).then(function(c) {
    if (c.error) {
      el.innerHTML = '<h1>Not found</h1><p class="lede">' + esc(c.error) + '</p>';
      return;
    }
    detailComponent = c;
    setActiveNav(CATEGORY_TO_SECTION[c.category] || '');
    if (c.component_type === 'output') {
      loadOutputInstances(c).then(renderComponentDetailBody);
    } else if (c.component_type === 'theme') {
      loadThemeInstances(c).then(renderComponentDetailBody);
    } else {
      renderComponentDetailBody();
    }
  }).catch(function() {
    el.innerHTML = '<h1>Error</h1><p class="lede">Could not load this component.</p>';
  });
}

function renderComponentDetail(id) {
  var el = document.getElementById('section-component');
  if (!id) {
    el.innerHTML = '<h1>Component</h1><p class="lede">Not found.</p>';
    return;
  }
  if (!detailComponent || detailComponent.id !== id) {
    detailEdits = {};
    detailReplacingSecret = {};
    detailOutputsWorking = null;
    detailOutputType = null;
    detailThemeName = null;
    detailAdvancedOpen = false;
    hasUnsavedComponentEdits = false;
    el.innerHTML = '<h1>Loading…</h1>';
    fetchComponentDetail(id);
    return;
  }
  renderComponentDetailBody();
}

function saveDetailComponent() {
  var c = detailComponent;
  var statusEl = document.getElementById('detail-save-status');
  statusEl.textContent = 'Saving…';
  statusEl.className = '';

  var body;
  if (c.component_type === 'output' || c.component_type === 'theme') {
    var outputsPayload = {};
    outputsPayload[detailOutputType] = detailOutputsWorking;
    body = { outputs: outputsPayload };
  } else {
    var values = {};
    Object.keys(detailEdits).forEach(function(name) {
      values[c.config_path + '.' + name] = detailEdits[name];
    });
    body = { values: values };
  }

  fetch('/api/config/form', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (!d.ok) {
      statusEl.textContent = d.error || 'Save failed.';
      statusEl.className = 'err';
      return;
    }
    detailPendingStatus = {
      text: d.restart_required
        ? 'Saved. A restart is needed for outputs/authentication changes to take effect.'
        : 'Saved - changes take effect within a few seconds.',
      className: 'ok',
    };
    hasUnsavedComponentEdits = false;
    detailEdits = {};
    detailReplacingSecret = {};
    fetchComponentDetail(c.id);
    fetchDashboard();
  }).catch(function() {
    statusEl.textContent = 'Request failed.';
    statusEl.className = 'err';
  });
}

function discardDetailEdits() {
  if (!confirm('Discard unsaved changes?')) return;
  detailEdits = {};
  detailReplacingSecret = {};
  hasUnsavedComponentEdits = false;
  fetchComponentDetail(detailComponent.id);
}

function runDetailTest() {
  var c = detailComponent;
  var btn = document.getElementById('detail-test-btn');
  var resultEl = document.getElementById('detail-test-result');
  btn.disabled = true;
  btn.textContent = 'Testing…';
  resultEl.className = 'test-result show';
  resultEl.textContent = 'Running…';

  var typeName = c.config_path.split('.')[1];
  var req;
  if (c.component_type === 'source') {
    req = fetch('/api/test/source/' + encodeURIComponent(typeName), { method: 'POST' });
  } else if (c.component_type === 'enricher') {
    req = fetch('/api/test/enricher/' + encodeURIComponent(typeName), { method: 'POST' });
  } else if (c.component_type === 'output') {
    var body = Object.assign({ type: typeName }, detailOutputsWorking[0]);
    req = fetch('/api/test/output', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
  } else {
    return;
  }

  req.then(function(r) { return r.json(); }).then(function(d) {
    resultEl.classList.add(d.ok ? 'ok' : 'fail');
    resultEl.textContent = d.message;
  }).catch(function() {
    resultEl.classList.add('fail');
    resultEl.textContent = 'Request failed.';
  }).finally(function() {
    btn.disabled = false;
    btn.textContent = 'Test connection';
  });
}

// ---------------------------------------------------------------------
// Health - action-oriented status list (Fas 6). Only components with a
// real live health signal: sources/idle sources/enrichers/outputs -
// themes/text_enrichers/flat sections always report health: "unknown"
// (see ui_builder.py), same scope as the classic Status page's
// /api/status. Filtering/search update visibility in place (no
// re-render) so the search input never loses focus mid-keystroke - full
// re-renders only happen on navigation or the 15s poll refresh.
// ---------------------------------------------------------------------
var HEALTH_TYPE_GROUPS = [
  { type: 'source', label: 'Sources' },
  { type: 'idle_source', label: 'Idle screen' },
  { type: 'enricher', label: 'Enrichers' },
  { type: 'output', label: 'Displays' },
];
var healthStatusFilter = 'all';
var healthSearchQuery = '';

function healthCardMatches(c) {
  var statusOk = healthStatusFilter === 'all' || c.status === healthStatusFilter;
  var searchOk = !healthSearchQuery || c.name.toLowerCase().indexOf(healthSearchQuery.toLowerCase()) !== -1;
  return statusOk && searchOk;
}

function applyHealthFilters() {
  document.querySelectorAll('#section-health .health-card').forEach(function(card) {
    var c = componentsById[card.dataset.id];
    card.classList.toggle('hidden', !(c && healthCardMatches(c)));
  });
  document.querySelectorAll('#section-health .health-group').forEach(function(group) {
    var anyVisible = false;
    group.querySelectorAll('.health-card').forEach(function(card) {
      if (!card.classList.contains('hidden')) anyVisible = true;
    });
    group.classList.toggle('hidden', !anyVisible);
  });
  document.querySelectorAll('#section-health .chip[data-health-filter]').forEach(function(chip) {
    chip.classList.toggle('active', chip.dataset.healthFilter === healthStatusFilter);
  });
}

function onHealthFilterClick(filter) {
  healthStatusFilter = filter;
  applyHealthFilters();
}
function onHealthSearchInput(value) {
  healthSearchQuery = value;
  applyHealthFilters();
}

// Sources/enrichers test the last *saved* config (no body - matches
// components.js's own runDetailTest() and the classic shell's source/
// enricher test, both of which read from disk server-side). Outputs
// deliberately get a link to their detail page instead of an inline
// test button here - see the module-level plan notes: /api/test/output
// needs the instance's actual current field values in the request body,
// which this list view doesn't hold (only the detail page does).
function runHealthTest(btn) {
  var kind = btn.dataset.componentType;
  var typeName = btn.dataset.typeName;
  var resultEl = btn.nextElementSibling;
  btn.disabled = true;
  btn.textContent = 'Testing…';
  resultEl.className = 'test-result show';
  resultEl.textContent = 'Running…';

  var url = kind === 'source'
    ? '/api/test/source/' + encodeURIComponent(typeName)
    : '/api/test/enricher/' + encodeURIComponent(typeName);

  fetch(url, { method: 'POST' }).then(function(r) { return r.json(); }).then(function(d) {
    resultEl.classList.add(d.ok ? 'ok' : 'fail');
    resultEl.textContent = d.message;
  }).catch(function() {
    resultEl.classList.add('fail');
    resultEl.textContent = 'Request failed.';
  }).finally(function() {
    btn.disabled = false;
    btn.textContent = 'Test connection';
  });
}

function healthTestControl(c) {
  if (c.component_type === 'output') {
    return '<a class="btn secondary small" href="#component/' + esc(c.id) + '">Test connection →</a>';
  }
  if (!c.supports_test) return '';
  var typeName = c.config_path.split('.')[1];
  return '<button type="button" class="btn secondary small" onclick="runHealthTest(this)" '
    + 'data-component-type="' + esc(c.component_type) + '" data-type-name="' + esc(typeName) + '">Test connection</button>';
}

function healthCard(c) {
  var warningText = (c.warnings && c.warnings.length) ? c.warnings[0] : '';
  return '<div class="component-card health-card" data-id="' + esc(c.id) + '">'
    + '<a class="body" href="#component/' + esc(c.id) + '">'
    + '<div class="name">' + esc(c.name) + '</div>'
    + '<span class="badge b-' + esc(c.status) + '">' + esc(STATUS_LABELS[c.status] || c.status) + '</span>'
    + (warningText ? '<div class="warning">' + esc(warningText) + '</div>' : '')
    + '</a>'
    + '<div class="test-row">' + healthTestControl(c) + '<div class="test-result" id="test-result-' + esc(c.id) + '"></div></div>'
    + '</div>';
}

function renderHealthSection() {
  var el = document.getElementById('section-health');
  if (!componentsData) {
    el.innerHTML = '<h1>Health</h1><p class="lede">Loading…</p>';
    return;
  }

  var html = '<h1>Health</h1><p class="lede">Live status for everything that reports one, with quick actions where they help.</p>';

  html += '<a class="component-card" href="#component/alerts" style="display:block;max-width:360px;margin-bottom:14px;">'
    + '<div class="body"><div class="name">Configure alerting →</div>'
    + '<div class="desc">Get notified when a source or output has been failing for a while.</div></div></a>';

  if (dashboardData && dashboardData.restart_required) {
    html += '<div class="card" style="border-color:var(--warn);margin-bottom:14px;">'
      + '<div class="row" style="display:flex;align-items:center;justify-content:space-between;gap:10px;">'
      + '<span>A restart is needed for recent display/authentication changes to take effect.</span>'
      + '<button type="button" class="btn danger small" onclick="runRestartAction(\'/api/restart\')">Restart mediainfo</button>'
      + '</div></div>';
  }

  html += '<div class="filters">'
    + ['all', 'connected', 'needs_configuration', 'error', 'disabled'].map(function(f) {
      return '<button type="button" class="chip' + (healthStatusFilter === f ? ' active' : '') + '" '
        + 'data-health-filter="' + f + '" onclick="onHealthFilterClick(\'' + f + '\')">'
        + esc(f === 'all' ? 'All' : (STATUS_LABELS[f] || f)) + '</button>';
    }).join('')
    + '<input type="text" id="health-search" placeholder="Search…" aria-label="Search health items by name" '
    + 'value="' + esc(healthSearchQuery) + '" oninput="onHealthSearchInput(this.value)">'
    + '</div>';

  HEALTH_TYPE_GROUPS.forEach(function(group) {
    var items = componentsData.filter(function(c) { return c.component_type === group.type; });
    if (!items.length) return;
    html += '<div class="health-group">'
      + '<h2 class="group-title">' + esc(group.label) + '</h2>'
      + '<div class="component-list">' + items.map(healthCard).join('') + '</div>'
      + '</div>';
  });

  el.innerHTML = html;
  applyHealthFilters();
}
