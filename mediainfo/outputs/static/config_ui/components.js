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
// same endpoints the classic shell (now gone - see ADR 0001/H5) used:
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
    { type: 'theme_group_editor', label: 'Groups' },
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
  var badge = '<span class="badge b-' + esc(c.status) + '">' + esc(STATUS_LABELS[c.status] || c.status) + '</span>';
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
  var sectionItems = componentsData.filter(function(c) { return c.category === category; });
  var html = '<h1>' + esc(SECTION_TITLES[name]) + '</h1><p class="lede">Click a component to view or edit its settings.</p>';
  html += filterBarHtml(name, sectionItems);
  var any = false;
  groups.forEach(function(group) {
    var items = sectionItems.filter(function(c) { return c.component_type === group.type; });
    if (!items.length) return;
    any = true;
    html += '<div class="card-group">';
    if (groups.length > 1) html += '<h2 class="group-title">' + esc(group.label) + '</h2>';
    html += '<div class="card-grid">' + items.map(function(c) { return cardTile(c, componentCard(c)); }).join('') + '</div>';
    html += '</div>';
  });
  if (!any) html += '<div class="card"><span class="field-help">Nothing here yet.</span></div>';
  el.innerHTML = html;
  applyCardFilters(name);
}

// ---------------------------------------------------------------------
// Component detail page - local edit state
// ---------------------------------------------------------------------
var detailComponent = null;          // last-fetched UiComponent for the current detail page
var detailEdits = {};                // non-output/theme: fieldName -> new value
var detailReplacingSecret = {};      // fieldName -> true while its "Replace" input is open
var detailOutputsWorking = null;     // output/theme: full instance array (deep copy) for the owning output type
var detailOutputType = null;         // output type name detailOutputsWorking belongs to
var detailInstanceIndex = 0;         // output only: which detailOutputsWorking[] entry is shown/edited (see the instance picker in renderComponentDetailBody())
var detailThemeName = null;          // set only for component_type "theme"
var detailAdvancedOpen = false;
var detailFiltersOpen = false;
// theme_group_editor only: available theme names + trigger media types for
// the groups editor's multi-selects, fetched alongside /api/config (see
// loadAutoRotateInstances) - not stored anywhere else in this file, since
// this is the only view that needs schema data beyond a component's own
// already-resolved essential_fields/advanced_fields.
var detailAvailableThemeNames = [];
var detailAvailableMediaTypes = [];
var detailNewGroupName = '';         // theme_group_editor's "+ Add group" name input, kept across re-renders
// A save's confirmation ("Saved - changes take effect...") is set on the
// *current* #detail-save-status element, but the save handler immediately
// triggers a refetch to show fresh server state (flips secret badges
// etc.) - that refetch's own render replaces the whole section, including
// a brand new (empty) #detail-save-status, wiping the message out before
// anyone can read it. Stashing it here and having
// renderComponentDetailBody() apply it once after that fresh render lands
// avoids the race instead of racing the DOM directly.
var detailPendingStatus = null;

function findDetailField(name) {
  var all = (detailComponent.essential_fields || []).concat(detailComponent.advanced_fields || []);
  for (var i = 0; i < all.length; i++) {
    if (all[i].name === name) return all[i];
  }
  return { name: name };
}

function getFieldValue(field) {
  if (detailComponent.component_type === 'output') {
    var instance = detailOutputsWorking[detailInstanceIndex];
    return instance ? instance[field.name] : field.value;
  }
  if (detailComponent.component_type === 'theme') {
    return detailOutputsWorking[0].themes[detailThemeName][field.name];
  }
  if (detailComponent.component_type === 'theme_group_editor') {
    return detailOutputsWorking[0].auto_rotate[field.name];
  }
  return Object.prototype.hasOwnProperty.call(detailEdits, field.name) ? detailEdits[field.name] : field.value;
}

function setFieldValue(field, value) {
  hasUnsavedComponentEdits = true;
  if (detailComponent.component_type === 'output') {
    detailOutputsWorking[detailInstanceIndex][field.name] = value;
  } else if (detailComponent.component_type === 'theme') {
    detailOutputsWorking[0].themes[detailThemeName][field.name] = value;
  } else if (detailComponent.component_type === 'theme_group_editor') {
    detailOutputsWorking[0].auto_rotate[field.name] = value;
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

// A flat list-of-strings field (see config_schema.py's _SIMPLE_LIST_FIELDS).
// Two shapes, matching app.html's own two patterns for this: a known set of
// values (field.choices, e.g. transition_exclude) gets a toggle-button row
// (same pattern as the theme_group_editor's renderGroupsEditor() toggleBtns,
// itself adapted from app.html's renderOutputFilters()); an open-ended list
// (e.g. device_ips, one IP per line) gets a one-item-per-line textarea,
// exactly app.html's listToTextarea()/textareaToList().
function listToTextarea(value) {
  return Array.isArray(value) ? value.join('\n') : '';
}
function textareaToList(text) {
  return text.split('\n').map(function(s) { return s.trim(); }).filter(Boolean);
}
function onListChoiceToggle(name, choiceValue) {
  var field = findDetailField(name);
  var items = (getFieldValue(field) || []).slice();
  var idx = items.indexOf(choiceValue);
  if (idx === -1) items.push(choiceValue); else items.splice(idx, 1);
  onDetailFieldChange(name, items);
}

// "HH:MM-HH:MM" fields (active_hours, screen_off_hours) - two <input
// type="time"> plus Clear, adapted from app.html's time-range control.
// Unlike app.html's onTimeRangeChange() (which joins start/end unconditionally,
// so filling one side while the other is still blank saves/re-renders as ""
// and visibly wipes out what was just typed - reproduced live while building
// this), a change with exactly one side filled is treated as "still editing"
// and skipped rather than saved: setting a fresh range means filling start
// then end, and the first of those two changes must not clobber it. Only
// "both filled" (a complete range) or "both blank" (fully cleared) commit.
function onDetailTimeRangeChange(name, containerEl) {
  var start = containerEl.querySelector('[data-part="start"]').value;
  var end = containerEl.querySelector('[data-part="end"]').value;
  if (Boolean(start) !== Boolean(end)) return;
  onDetailFieldChange(name, (start && end) ? (start + '-' + end) : '');
}

function renderTimeRangeField(field, value) {
  var parts = (value || '').split('-');
  var start = parts[0] || '', end = parts[1] || '';
  var onchange = "onDetailTimeRangeChange('" + esc(field.name) + "', this.parentElement)";
  var control = '<div class="time-range-row">'
    + '<input type="time" value="' + esc(start) + '" aria-label="' + esc(field.label) + ' start time" data-part="start" onchange="' + onchange + '">'
    + '<span aria-hidden="true">to</span>'
    + '<input type="time" value="' + esc(end) + '" aria-label="' + esc(field.label) + ' end time" data-part="end" onchange="' + onchange + '">'
    + '<button type="button" class="link-btn" onclick="onDetailFieldChange(\'' + esc(field.name) + '\', \'\')">Clear</button>'
    + '</div>';
  return '<div class="field"><div class="field-row">'
    + '<label class="field-label">' + esc(field.label) + '</label>'
    + '<div class="field-control">' + control
    + (field.help ? '<div class="field-help">' + esc(field.help) + '</div>' : '')
    + '</div></div></div>';
}

// brightness_schedule: a list of "HH:MM-HH:MM=<level>" strings (first
// matching window wins), e.g. pixoo/ulanzi's brightness_schedule. Ported
// from app.html's renderBrightnessScheduleWidget()/onOutputScheduleRow()/
// Add()/Remove() - but every edit re-renders through the same
// onDetailFieldChange() path as every other widget here (app.html's
// version mutates outputsData in place without re-rendering on a row-value
// change, only on add/remove, to dodge exactly the "reset a field that's
// still mid-edit" bug the time_range widget above hit; +Add here seeds a
// new row with a complete, valid default (00:00-00:00=100) rather than a
// blank one, so there's never an incomplete in-progress row for a re-render
// to lose - the same dodge without the inconsistent re-render behavior).
function scheduleRowsFromValue(value) {
  return (value || []).map(function(s) {
    var m = /^(\d{2}:\d{2})-(\d{2}:\d{2})=(\d+)$/.exec(s || '');
    return m ? { start: m[1], end: m[2], level: m[3] } : { start: '', end: '', level: '' };
  });
}
function scheduleRowsToValue(rows) {
  return rows.filter(function(r) { return r.start && r.end && r.level !== ''; })
    .map(function(r) { return r.start + '-' + r.end + '=' + r.level; });
}
function onDetailScheduleRowChange(name, index, part, rawValue) {
  var field = findDetailField(name);
  var rows = scheduleRowsFromValue(getFieldValue(field));
  rows[index][part] = rawValue;
  onDetailFieldChange(name, scheduleRowsToValue(rows));
}
function onDetailScheduleAdd(name) {
  var field = findDetailField(name);
  var items = (getFieldValue(field) || []).slice();
  items.push('00:00-00:00=100');
  onDetailFieldChange(name, items);
}
function onDetailScheduleRemove(name, index) {
  var field = findDetailField(name);
  var items = (getFieldValue(field) || []).slice();
  items.splice(index, 1);
  onDetailFieldChange(name, items);
}

function renderBrightnessScheduleField(field, value) {
  var rows = scheduleRowsFromValue(value);
  var body = rows.map(function(r, i) {
    var fname = esc(field.name);
    return '<div class="schedule-row">'
      + '<input type="time" value="' + esc(r.start) + '" aria-label="Start time" '
      + 'onchange="onDetailScheduleRowChange(\'' + fname + '\', ' + i + ', \'start\', this.value)">'
      + '<span aria-hidden="true">to</span>'
      + '<input type="time" value="' + esc(r.end) + '" aria-label="End time" '
      + 'onchange="onDetailScheduleRowChange(\'' + fname + '\', ' + i + ', \'end\', this.value)">'
      + '<span aria-hidden="true">brightness</span>'
      + '<input type="number" min="0" value="' + esc(r.level) + '" aria-label="Brightness level" '
      + 'onchange="onDetailScheduleRowChange(\'' + fname + '\', ' + i + ', \'level\', this.value)">'
      + '<button type="button" class="link-btn" onclick="onDetailScheduleRemove(\'' + fname + '\', ' + i + ')">Remove</button>'
      + '</div>';
  }).join('');
  var control = '<div class="schedule-rows">' + body
    + '<button type="button" class="btn secondary small" onclick="onDetailScheduleAdd(\'' + esc(field.name) + '\')">+ Add time window</button>'
    + '</div>';
  return '<div class="field"><div class="field-row">'
    + '<label class="field-label">' + esc(field.label) + '</label>'
    + '<div class="field-control">' + control
    + (field.help ? '<div class="field-help">' + esc(field.help) + '</div>' : '')
    + '</div></div></div>';
}

function renderListField(field, value) {
  var items = Array.isArray(value) ? value : [];
  var control;
  if (field.choices) {
    control = '<div class="row-inline">' + field.choices.map(function(ch) {
      var active = items.indexOf(ch) !== -1;
      return '<button type="button" class="btn small ' + (active ? '' : 'secondary') + '" '
        + 'onclick="onListChoiceToggle(\'' + esc(field.name) + '\', \'' + esc(ch) + '\')">' + esc(ch) + '</button>';
    }).join('') + '</div>';
  } else {
    control = '<textarea placeholder="One per line" '
      + 'onchange="onDetailFieldChange(\'' + esc(field.name) + '\', textareaToList(this.value))">'
      + esc(listToTextarea(items)) + '</textarea>';
  }
  var reqMark = field.required ? '<span class="req">*</span>' : '';
  return '<div class="field"><div class="field-row">'
    + '<label class="field-label">' + esc(field.label) + reqMark + '</label>'
    + '<div class="field-control">' + control
    + (field.help ? '<div class="field-help">' + esc(field.help) + '</div>' : '')
    + '</div></div></div>';
}

function renderDetailField(field) {
  var value = getFieldValue(field);

  var control;
  if (field.secret) {
    control = renderSecretField(field, value);
  } else if (field.type === 'bool') {
    control = '<input type="checkbox" ' + (value ? 'checked' : '')
      + ' onchange="onDetailFieldChange(\'' + esc(field.name) + '\', this.checked)">';
  } else if (field.widget === 'time_range') {
    return renderTimeRangeField(field, value);
  } else if (field.widget === 'brightness_schedule') {
    return renderBrightnessScheduleField(field, value);
  } else if (field.type === 'list') {
    return renderListField(field, value);
  } else if (field.choices) {
    control = '<select onchange="onDetailFieldChange(\'' + esc(field.name) + '\', this.value)">'
      + field.choices.map(function(ch) {
        return '<option value="' + esc(ch) + '"' + (ch === value ? ' selected' : '') + '>' + esc(ch) + '</option>';
      }).join('') + '</select>';
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

  var html = wizardBannerHtml();
  html += '<a class="back-link" href="#' + esc(sectionName) + '">← Back to ' + esc(SECTION_TITLES[sectionName] || 'list') + '</a>';
  html += '<h1>' + esc(c.name) + '</h1>';
  if (c.description) html += '<p class="lede">' + esc(c.description) + '</p>';
  html += '<span class="badge b-' + esc(c.status) + '">' + esc(STATUS_LABELS[c.status] || c.status) + '</span>';

  if (c.warnings && c.warnings.length) {
    html += '<ul class="warning-list" style="margin-top:12px;">'
      + c.warnings.map(function(w) { return '<li class="warning-item">' + esc(w) + '</li>'; }).join('')
      + '</ul>';
  }

  if (c.component_type === 'output' && c.supports_multiple && detailOutputsWorking) {
    html += renderInstancePicker(c);
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

  if (c.filter_fields && c.filter_fields.length) {
    html += '<div class="card" style="margin-top:14px;">'
      + '<details class="advanced-toggle"' + (detailFiltersOpen ? ' open' : '') + ' ontoggle="detailFiltersOpen = this.open">'
      + '<summary>Content filters</summary>'
      + '<p class="field-help">Limit what this display shows - e.g. only music, or never a specific source.</p>'
      + c.filter_fields.map(renderDetailField).join('')
      + '</details></div>';
  }

  if (c.component_type === 'theme_group_editor') {
    html += renderGroupsEditor();
  }

  if (c.id === 'sources.appletv') {
    html += '<div class="card" style="margin-top:14px;">' + renderAppletvPairing() + '</div>';
  }
  if (c.id === 'outputs.pixoo') {
    html += renderPixooPreview();
  }

  html += '<div class="action-row">';
  if (c.supports_test) {
    html += '<button type="button" class="btn secondary" id="detail-test-btn" onclick="runDetailTest()">Test connection</button>';
  }
  html += '<button type="button" class="btn secondary" onclick="discardDetailEdits()">Discard</button>';
  html += '<button type="button" class="btn" onclick="saveDetailComponent()">Save</button>';
  html += '</div>';
  html += '<div class="test-result" id="detail-test-result"></div>';
  html += '<div id="detail-save-status" style="margin-top:8px;font-size:12.5px;"></div>';

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

// ---------------------------------------------------------------------
// Apple TV pairing wizard - shown only on the sources.appletv detail page
// (see renderComponentDetailBody() above), ported as-is from the classic
// shell. A local step machine (idle -> starting -> need_pin|
// need_manual_entry -> finishing -> done) talking to the existing
// /api/appletv/pair/{start,finish,cancel} endpoints; a successful finish
// stages the returned credentials/enabled flag into this component's own
// edit state via setFieldValue(), so "Save" below still goes through the
// normal saveDetailComponent() path - pairing itself never writes
// config.yaml directly.
// ---------------------------------------------------------------------
var appletvState = { step: 'idle', protocol: 'companion', devicePin: null, error: null };

function renderAppletvPairing() {
  var s = appletvState;
  var rows = '';
  if (s.step === 'idle') {
    rows = '<select id="appletv-protocol">'
      + '<option value="companion"' + (s.protocol === 'companion' ? ' selected' : '') + '>Companion (tvOS 15+)</option>'
      + '<option value="mrp"' + (s.protocol === 'mrp' ? ' selected' : '') + '>MRP (older devices)</option>'
      + '</select> <button type="button" class="btn secondary small" onclick="appletvPairStart()">Pair</button>';
  } else if (s.step === 'starting') {
    rows = '<span>Scanning and starting pairing…</span>';
  } else if (s.step === 'need_pin') {
    rows = '<div class="row-inline"><input type="text" id="appletv-pin" inputmode="numeric" placeholder="PIN shown on device" aria-label="Pairing PIN" style="width:140px;">'
      + '<button type="button" class="btn secondary small" onclick="appletvPairSubmit()">Submit PIN</button>'
      + '<button type="button" class="btn secondary small" onclick="appletvPairCancel()">Cancel</button></div>';
  } else if (s.step === 'need_manual_entry') {
    rows = '<p class="field-help">Enter <b>' + esc(s.devicePin) + '</b> on the Apple TV, then continue.</p>'
      + '<button type="button" class="btn secondary small" onclick="appletvPairSubmit()">Continue</button> '
      + '<button type="button" class="btn secondary small" onclick="appletvPairCancel()">Cancel</button>';
  } else if (s.step === 'finishing') {
    rows = '<span>Finishing pairing…</span>';
  } else if (s.step === 'done') {
    rows = '<p style="font-size:12px;color:var(--ok);">Paired - credentials staged below. Click Save to write them to config.yaml.</p>'
      + '<button type="button" class="btn secondary small" onclick="appletvPairReset()">Pair again</button>';
  }
  var error = s.error ? '<p class="field-error">' + esc(s.error) + '</p>' : '';
  return '<div class="field" id="appletv-pairing"><div class="field-row"><label class="field-label">Pairing wizard</label>'
    + '<div class="field-control" role="status" aria-live="polite">' + error + rows + '</div></div></div>';
}

function appletvRerender() {
  var el = document.getElementById('appletv-pairing');
  if (el) el.outerHTML = renderAppletvPairing();
}

function appletvPairStart() {
  var host = getFieldValue(findDetailField('host'));
  appletvState.protocol = document.getElementById('appletv-protocol').value;
  appletvState.step = 'starting'; appletvState.error = null;
  appletvRerender();
  apiFetch('/api/appletv/pair/start', {
    method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, CSRF_HEADERS),
    body: JSON.stringify({ host: host || '', protocol: appletvState.protocol }),
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (!d.ok) { appletvState.step = 'idle'; appletvState.error = d.error; }
    else if (d.device_provides_pin) { appletvState.step = 'need_pin'; }
    else { appletvState.step = 'need_manual_entry'; appletvState.devicePin = d.manual_pin; }
    appletvRerender();
  }).catch(function() { appletvState.step = 'idle'; appletvState.error = 'Request failed.'; appletvRerender(); });
}

function appletvPairSubmit() {
  var pinEl = document.getElementById('appletv-pin');
  var pin = pinEl ? pinEl.value : null;
  appletvState.step = 'finishing'; appletvRerender();
  apiFetch('/api/appletv/pair/finish', {
    method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, CSRF_HEADERS),
    body: JSON.stringify({ pin: pin }),
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (!d.ok) {
      appletvState.step = appletvState.devicePin ? 'need_manual_entry' : 'need_pin';
      appletvState.error = d.error;
      appletvRerender();
      return;
    }
    setFieldValue(findDetailField(d.field), d.credentials);
    setFieldValue(findDetailField('enabled'), true);
    appletvState.step = 'done';
    renderComponentDetailBody();
  }).catch(function() { appletvState.error = 'Request failed.'; appletvRerender(); });
}

function appletvPairCancel() {
  apiFetch('/api/appletv/pair/cancel', { method: 'POST', headers: CSRF_HEADERS }).catch(function() {});
  appletvState = { step: 'idle', protocol: appletvState.protocol, devicePin: null, error: null };
  appletvRerender();
}

function appletvPairReset() {
  appletvState = { step: 'idle', protocol: appletvState.protocol, devicePin: null, error: null };
  appletvRerender();
}

// ---------------------------------------------------------------------
// Pixoo LED preview - shown only on the pixoo output's detail page (see
// renderComponentDetailBody() above), for whichever instance the instance
// picker currently has selected. Ported from the classic shell's
// renderPixooPreview()/runPixooPreview(), using
// detailOutputsWorking[detailInstanceIndex] (this page's own "current,
// possibly unsaved settings" state) instead of app.html's flat
// outputsData, so previewing never requires saving first here either.
// ---------------------------------------------------------------------
function renderPixooPreview() {
  return '<div class="card" style="margin-top:14px;">'
    + '<details class="advanced-toggle" open><summary>LED preview</summary>'
    + '<div class="field-help">Upload a poster/album cover to see how it will look on the LED display with the settings above.</div>'
    + '<div class="row-inline" style="margin-top:8px;">'
    + '<input type="file" accept="image/*" id="pixoo-preview-file">'
    + '<button type="button" class="btn secondary small" onclick="runPixooPreview()">Generate preview</button>'
    + '</div>'
    + '<div class="test-result" id="pixoo-preview-error"></div>'
    + '<div class="pixoo-preview-grid" id="pixoo-preview-grid" style="display:none;">'
    + '<div class="pixoo-preview-cell"><img id="pixoo-preview-original"><div class="caption">Original</div></div>'
    + '<div class="pixoo-preview-cell"><img id="pixoo-preview-cropped"><div class="caption">Cropped</div></div>'
    + '<div class="pixoo-preview-cell"><img id="pixoo-preview-final" class="pixelated"><div class="caption">Final (native size)</div></div>'
    + '<div class="pixoo-preview-cell"><img id="pixoo-preview-upscaled" class="pixelated"><div class="caption">Final (enlarged)</div></div>'
    + '</div>'
    + '</details></div>';
}

function runPixooPreview() {
  var fileInput = document.getElementById('pixoo-preview-file');
  var errorEl = document.getElementById('pixoo-preview-error');
  var gridEl = document.getElementById('pixoo-preview-grid');
  var file = fileInput && fileInput.files && fileInput.files[0];
  if (!file) {
    errorEl.className = 'test-result show fail'; errorEl.textContent = 'Choose an image first.';
    return;
  }
  var settings = detailOutputsWorking[detailInstanceIndex];
  var form = new FormData();
  form.append('file', file);
  form.append('settings', JSON.stringify(settings));

  errorEl.className = 'test-result show'; errorEl.textContent = 'Generating…';
  gridEl.style.display = 'none';
  apiFetch('/api/preview/pixoo', { method: 'POST', headers: CSRF_HEADERS, body: form })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.ok) { errorEl.className = 'test-result show fail'; errorEl.textContent = d.error || 'Preview failed.'; return; }
      document.getElementById('pixoo-preview-original').src = 'data:image/png;base64,' + d.original;
      document.getElementById('pixoo-preview-cropped').src = 'data:image/png;base64,' + d.cropped;
      document.getElementById('pixoo-preview-final').src = 'data:image/png;base64,' + d.final;
      document.getElementById('pixoo-preview-upscaled').src = 'data:image/png;base64,' + d.final_upscaled;
      errorEl.className = 'test-result'; errorEl.textContent = '';
      gridEl.style.display = 'grid';
    })
    .catch(function() { errorEl.className = 'test-result show fail'; errorEl.textContent = 'Request failed.'; });
}

// theme_group_editor: auto_rotate.presets bespoke editor - a toggle-button
// multi-select per group for both its themes and its `when` trigger media
// types, adapted from app.html's renderOutputFilters()/toggleFilterMediaType()
// pattern. Add/remove only (no rename) - all edits mutate
// detailOutputsWorking[0].auto_rotate.presets directly, same
// mutate-then-re-render convention as every other detail-page control.
function renderGroupsEditor() {
  var presets = detailOutputsWorking[0].auto_rotate.presets;
  var names = Object.keys(presets);

  function toggleBtns(active, allValues, onclickName, groupName) {
    return allValues.map(function(v) {
      var isActive = active.indexOf(v) !== -1;
      return '<button type="button" class="btn small ' + (isActive ? '' : 'secondary') + '" '
        + 'onclick="' + onclickName + '(\'' + esc(groupName) + '\',\'' + esc(v) + '\')">' + esc(v) + '</button>';
    }).join('');
  }

  var html = '<div class="card" style="margin-top:14px;">';
  if (!names.length) {
    html += '<span class="field-help">No groups yet - every enabled theme shows at once.</span>';
  }
  names.forEach(function(name) {
    var group = presets[name];
    if (!group.themes) group.themes = [];
    if (!group.when) group.when = [];
    html += '<div class="field" style="border-top:1px solid var(--border);padding-top:12px;margin-top:12px;">';
    html += '<div class="field-row"><label class="field-label">' + esc(name) + '</label>'
      + '<div class="field-control"><button type="button" class="btn secondary small" '
      + 'onclick="removeGroup(\'' + esc(name) + '\')">Remove group</button></div></div>';
    html += '<div class="field-row"><label class="field-label">Themes</label><div class="field-control">'
      + '<div class="row-inline">' + toggleBtns(group.themes, detailAvailableThemeNames, 'toggleGroupTheme', name) + '</div></div></div>';
    html += '<div class="field-row"><label class="field-label">Show only for</label><div class="field-control">'
      + '<div class="row-inline">' + toggleBtns(group.when, detailAvailableMediaTypes, 'toggleGroupWhen', name) + '</div>'
      + '<div class="field-help">Empty = takes part in the timer-based rotation above instead of a specific media type.</div></div></div>';
    html += '</div>';
  });
  html += '<div class="field-row" style="margin-top:12px;"><label class="field-label">New group</label>'
    + '<div class="field-control">'
    + '<input type="text" placeholder="Group name" value="' + esc(detailNewGroupName) + '" '
    + 'oninput="detailNewGroupName = this.value">'
    + ' <button type="button" class="btn small" onclick="addGroup()">Add group</button>'
    + '</div></div>';
  html += '</div>';
  return html;
}

function toggleGroupTheme(groupName, themeName) {
  var group = detailOutputsWorking[0].auto_rotate.presets[groupName];
  var pos = group.themes.indexOf(themeName);
  if (pos !== -1) group.themes.splice(pos, 1); else group.themes.push(themeName);
  hasUnsavedComponentEdits = true;
  renderComponentDetailBody();
}

function toggleGroupWhen(groupName, mediaType) {
  var group = detailOutputsWorking[0].auto_rotate.presets[groupName];
  var pos = group.when.indexOf(mediaType);
  if (pos !== -1) group.when.splice(pos, 1); else group.when.push(mediaType);
  hasUnsavedComponentEdits = true;
  renderComponentDetailBody();
}

function addGroup() {
  var name = (detailNewGroupName || '').trim();
  if (!name) return;
  var presets = detailOutputsWorking[0].auto_rotate.presets;
  if (Object.prototype.hasOwnProperty.call(presets, name)) return;
  presets[name] = { themes: [], when: [] };
  detailNewGroupName = '';
  hasUnsavedComponentEdits = true;
  renderComponentDetailBody();
}

function removeGroup(groupName) {
  delete detailOutputsWorking[0].auto_rotate.presets[groupName];
  hasUnsavedComponentEdits = true;
  renderComponentDetailBody();
}

function loadOutputInstances(c) {
  var typeName = c.config_path.split('.')[1];
  return apiFetch('/api/config').then(function(r) { return r.json(); }).then(function(cfg) {
    var instances = (cfg.outputs && cfg.outputs[typeName]) || [];
    detailOutputType = typeName;
    detailOutputsWorking = JSON.parse(JSON.stringify(instances));
    if (!detailOutputsWorking.length) detailOutputsWorking.push({});
    // Clamp rather than reset to 0 - renderComponentDetail() already resets
    // this to 0 when navigating to a *different* component; a post-save
    // reload (fetchComponentDetail() called directly, same component)
    // should keep showing whichever instance the save was for.
    detailInstanceIndex = Math.max(0, Math.min(detailInstanceIndex, detailOutputsWorking.length - 1));
  });
}

// Multi-instance outputs (H5 M6, e.g. two `ulanzi` or `folder` entries in
// config.yaml) - ported from app.html's blankOutputInstance()/
// addOutputInstance()/duplicateOutputInstance()/removeOutputInstance().
// Every essential_fields/advanced_fields/filter_fields entry already
// carries its own schema default (see config_schema.py's _scalar_fields()/
// _output_filter_fields()), so a blank instance is built generically from
// whatever fields this component's schema says it has, rather than a
// hand-maintained per-type list.
function blankOutputInstance(c) {
  var blank = {};
  (c.essential_fields || []).concat(c.advanced_fields || []).concat(c.filter_fields || [])
    .forEach(function(f) { blank[f.name] = f.default; });
  return blank;
}

function addOutputInstance() {
  detailOutputsWorking.push(blankOutputInstance(detailComponent));
  detailInstanceIndex = detailOutputsWorking.length - 1;
  hasUnsavedComponentEdits = true;
  renderComponentDetailBody();
}

function duplicateOutputInstance() {
  var copy = JSON.parse(JSON.stringify(detailOutputsWorking[detailInstanceIndex]));
  copy.label = copy.label ? copy.label + ' (copy)' : '';
  detailOutputsWorking.push(copy);
  detailInstanceIndex = detailOutputsWorking.length - 1;
  hasUnsavedComponentEdits = true;
  renderComponentDetailBody();
}

function removeOutputInstance() {
  var name = detailOutputsWorking[detailInstanceIndex].label || ('instance #' + (detailInstanceIndex + 1));
  if (!confirm('Remove this ' + esc(detailComponent.name) + ' ' + name + '? This needs a restart to take effect.')) return;
  detailOutputsWorking.splice(detailInstanceIndex, 1);
  if (!detailOutputsWorking.length) detailOutputsWorking.push(blankOutputInstance(detailComponent));
  detailInstanceIndex = Math.max(0, Math.min(detailInstanceIndex, detailOutputsWorking.length - 1));
  hasUnsavedComponentEdits = true;
  renderComponentDetailBody();
}

function selectOutputInstance(idx) {
  detailInstanceIndex = idx;
  renderComponentDetailBody();
}

function renderInstancePicker(c) {
  var tabs = detailOutputsWorking.map(function(inst, i) {
    var label = inst.label || ('Instance #' + (i + 1));
    return '<button type="button" class="btn small ' + (i === detailInstanceIndex ? '' : 'secondary') + '" '
      + 'onclick="selectOutputInstance(' + i + ')">' + esc(label) + '</button>';
  }).join('');
  return '<div class="card" style="margin-top:14px;">'
    + '<div class="row-inline">' + tabs
    + '<button type="button" class="btn secondary small" onclick="addOutputInstance()">+ Add another</button>'
    + '</div>'
    + '<div class="action-row" style="margin-top:10px;">'
    + '<button type="button" class="btn secondary" onclick="duplicateOutputInstance()">Duplicate this instance</button>'
    + (detailOutputsWorking.length > 1
      ? '<button type="button" class="btn secondary" onclick="removeOutputInstance()">Remove this instance</button>'
      : '')
    + '</div></div>';
}

function loadThemeInstances(c) {
  var themeName = c.config_path.split('.')[1];
  return apiFetch('/api/config').then(function(r) { return r.json(); }).then(function(cfg) {
    var instances = (cfg.outputs && cfg.outputs.themes) || [];
    detailOutputType = 'themes';
    detailThemeName = themeName;
    detailOutputsWorking = JSON.parse(JSON.stringify(instances));
    if (!detailOutputsWorking.length) detailOutputsWorking.push({});
    if (!detailOutputsWorking[0].themes) detailOutputsWorking[0].themes = {};
    if (!detailOutputsWorking[0].themes[themeName]) detailOutputsWorking[0].themes[themeName] = {};
  });
}

function loadAutoRotateInstances(c) {
  return Promise.all([
    apiFetch('/api/config').then(function(r) { return r.json(); }),
    apiFetch('/api/schema').then(function(r) { return r.json(); }),
  ]).then(function(results) {
    var cfg = results[0], schema = results[1];
    var instances = (cfg.outputs && cfg.outputs.themes) || [];
    detailOutputType = 'themes';
    detailOutputsWorking = JSON.parse(JSON.stringify(instances));
    if (!detailOutputsWorking.length) detailOutputsWorking.push({});
    if (!detailOutputsWorking[0].auto_rotate) detailOutputsWorking[0].auto_rotate = {};
    if (!detailOutputsWorking[0].auto_rotate.presets) detailOutputsWorking[0].auto_rotate.presets = {};
    // Normalize the legacy plain-list shape (a preset with no `when`,
    // e.g. {"minimal": ["glow"]}) into the {themes, when} object shape
    // uniformly, mirroring parse_presets() on the Python side - everything
    // below assumes group.themes/group.when exist.
    var presets = detailOutputsWorking[0].auto_rotate.presets;
    Object.keys(presets).forEach(function(name) {
      if (Array.isArray(presets[name])) {
        presets[name] = { themes: presets[name], when: [] };
      }
    });
    detailAvailableThemeNames = Object.keys(schema.themes || {});
    detailAvailableMediaTypes = (schema.auto_rotate_meta || {}).media_types || [];
    detailNewGroupName = '';
  });
}

function fetchComponentDetail(id) {
  var el = document.getElementById('section-component');
  apiFetch('/api/ui/component/' + encodeURIComponent(id)).then(function(r) { return r.json(); }).then(function(c) {
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
    } else if (c.component_type === 'theme_group_editor') {
      loadAutoRotateInstances(c).then(renderComponentDetailBody);
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
    detailInstanceIndex = 0;
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
  if (c.component_type === 'output' || c.component_type === 'theme' || c.component_type === 'theme_group_editor') {
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

  apiFetch('/api/config/form', {
    method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, CSRF_HEADERS),
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
    req = apiFetch('/api/test/source/' + encodeURIComponent(typeName), { method: 'POST', headers: CSRF_HEADERS });
  } else if (c.component_type === 'enricher') {
    req = apiFetch('/api/test/enricher/' + encodeURIComponent(typeName), { method: 'POST', headers: CSRF_HEADERS });
  } else if (c.component_type === 'output') {
    var body = Object.assign({ type: typeName }, detailOutputsWorking[0]);
    req = apiFetch('/api/test/output', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, CSRF_HEADERS),
      body: JSON.stringify(body),
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
// Card grid: filtering + per-card hide (Fas 8), shared by Media/Metadata/
// Appearance/Displays/Health. A component can appear on more than one of
// these pages (e.g. a source shows on both Media and Health), so "hide"
// is one global id set, not five independent ones - hide it from either
// page and it disappears from both. Kept in localStorage: this is a
// personal display preference, not config, so it doesn't touch
// config.yaml or need a new API endpoint.
//
// Filtering (status chips + name search) reuses the exact in-place
// DOM class-toggling approach Health's filter bar introduced in Fas 6
// (toggle a "hidden" class rather than re-render), generalized to any
// section: the search input never loses focus mid-keystroke, including
// under the 15s poll tick (see dashboard.js's fetchComponents()).
// ---------------------------------------------------------------------
var HEALTH_TYPE_GROUPS = [
  { type: 'source', label: 'Sources' },
  { type: 'idle_source', label: 'Idle screen' },
  { type: 'enricher', label: 'Enrichers' },
  { type: 'output', label: 'Displays' },
];
var CARD_STATUS_FILTERS = ['all', 'connected', 'needs_configuration', 'warning', 'error', 'disabled'];
var sectionFilterState = {};

function getSectionFilterState(sectionName) {
  if (!sectionFilterState[sectionName]) sectionFilterState[sectionName] = { status: 'all', query: '' };
  return sectionFilterState[sectionName];
}

function loadHiddenCardIds() {
  try {
    var raw = localStorage.getItem('mediainfo-hidden-card-ids');
    return new Set(raw ? JSON.parse(raw) : []);
  } catch (e) {
    return new Set();
  }
}
var hiddenCardIds = loadHiddenCardIds();
function saveHiddenCardIds() {
  try { localStorage.setItem('mediainfo-hidden-card-ids', JSON.stringify(Array.from(hiddenCardIds))); } catch (e) {}
}

// Wraps any card's HTML (componentCard()/healthCard()) with a hide/unhide
// overlay button - deliberately NOT baked into componentCard() itself,
// since Library's settings cards call componentCard() directly and must
// stay exactly as they were (no grid, no hide button, no filter bar).
function cardTile(c, innerHtml) {
  var isHidden = hiddenCardIds.has(c.id);
  return '<div class="card-tile" data-id="' + esc(c.id) + '">'
    + '<button type="button" class="card-hide-btn" title="' + (isHidden ? 'Unhide' : 'Hide') + '" '
    + 'aria-label="' + esc((isHidden ? 'Unhide ' : 'Hide ') + c.name) + '" '
    + 'onclick="toggleCardHidden(event, \'' + esc(c.id) + '\')">' + (isHidden ? '↺' : '×') + '</button>'
    + innerHtml
    + '</div>';
}

// Hiding/unhiding isn't a text field mid-keystroke, so a full re-render
// (rather than an in-place DOM tweak) is simplest and safe here.
function toggleCardHidden(event, id) {
  event.preventDefault();
  event.stopPropagation();
  if (hiddenCardIds.has(id)) hiddenCardIds.delete(id); else hiddenCardIds.add(id);
  saveHiddenCardIds();
  if (currentSection === 'health') renderHealthSection();
  else if (FILTERABLE_SECTIONS.indexOf(currentSection) !== -1) renderCategorySection(currentSection);
}

function filterBarHtml(sectionName, items) {
  var state = getSectionFilterState(sectionName);
  var hiddenCount = items.filter(function(c) { return hiddenCardIds.has(c.id); }).length;
  var chips = CARD_STATUS_FILTERS.map(function(f) {
    return '<button type="button" class="chip' + (state.status === f ? ' active' : '') + '" '
      + 'data-filter="' + f + '" onclick="onCardFilterClick(\'' + sectionName + '\', \'' + f + '\')">'
      + esc(f === 'all' ? 'All' : (STATUS_LABELS[f] || f)) + '</button>';
  }).join('');
  chips += '<button type="button" class="chip chip-hidden' + (state.status === 'hidden' ? ' active' : '') + '" '
    + 'data-filter="hidden" onclick="onCardFilterClick(\'' + sectionName + '\', \'hidden\')">'
    + 'Hidden (' + hiddenCount + ')</button>';
  return '<div class="filters">' + chips
    + '<input type="text" id="' + sectionName + '-search" class="filter-search-input" placeholder="Search…" '
    + 'aria-label="Search by name" value="' + esc(state.query) + '" '
    + 'oninput="onCardSearchInput(\'' + sectionName + '\', this.value)">'
    + '</div>';
}

function cardMatchesFilters(c, sectionName) {
  var state = getSectionFilterState(sectionName);
  var isHidden = hiddenCardIds.has(c.id);
  if (state.status === 'hidden') return isHidden;
  if (isHidden) return false;
  var statusOk = state.status === 'all' || c.status === state.status;
  var searchOk = !state.query || c.name.toLowerCase().indexOf(state.query.toLowerCase()) !== -1;
  return statusOk && searchOk;
}

function applyCardFilters(sectionName) {
  var sectionEl = document.getElementById('section-' + sectionName);
  if (!sectionEl) return;
  var hiddenCount = 0;
  sectionEl.querySelectorAll('.card-tile[data-id]').forEach(function(tile) {
    var c = componentsById[tile.dataset.id];
    if (c && hiddenCardIds.has(c.id)) hiddenCount++;
    tile.classList.toggle('hidden', !(c && cardMatchesFilters(c, sectionName)));
  });
  sectionEl.querySelectorAll('.card-group').forEach(function(group) {
    var anyVisible = false;
    group.querySelectorAll('.card-tile').forEach(function(tile) {
      if (!tile.classList.contains('hidden')) anyVisible = true;
    });
    group.classList.toggle('hidden', !anyVisible);
  });
  var state = getSectionFilterState(sectionName);
  sectionEl.querySelectorAll('.chip[data-filter]').forEach(function(chip) {
    chip.classList.toggle('active', chip.dataset.filter === state.status);
  });
  var hiddenChip = sectionEl.querySelector('.chip-hidden');
  if (hiddenChip) hiddenChip.textContent = 'Hidden (' + hiddenCount + ')';
}

function onCardFilterClick(sectionName, filter) {
  getSectionFilterState(sectionName).status = filter;
  applyCardFilters(sectionName);
}
function onCardSearchInput(sectionName, value) {
  getSectionFilterState(sectionName).query = value;
  applyCardFilters(sectionName);
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

  apiFetch(url, { method: 'POST', headers: CSRF_HEADERS }).then(function(r) { return r.json(); }).then(function(d) {
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
  // Health (status badge) and Activity (Fas 10) are shown as two
  // independent badges - a device can be Healthy and Sleeping at the
  // same time, that's the whole point of separating the two concepts.
  var activityBadge = c.activity
    ? '<span class="badge ' + esc(ACTIVITY_LABEL_CLASS[c.activity] || '') + '">' + esc(c.activity_label || c.activity) + '</span>'
    : '';
  return '<div class="component-card health-card">'
    + '<a class="body" href="#component/' + esc(c.id) + '">'
    + '<div class="name">' + esc(c.name) + '</div>'
    + '<span class="badge b-' + esc(c.status) + '">' + esc(STATUS_LABELS[c.status] || c.status) + '</span>'
    + activityBadge
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

  var healthItems = componentsData.filter(function(c) {
    return HEALTH_TYPE_GROUPS.some(function(g) { return g.type === c.component_type; });
  });

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

  html += filterBarHtml('health', healthItems);

  HEALTH_TYPE_GROUPS.forEach(function(group) {
    var items = healthItems.filter(function(c) { return c.component_type === group.type; });
    if (!items.length) return;
    html += '<div class="card-group">'
      + '<h2 class="group-title">' + esc(group.label) + '</h2>'
      + '<div class="card-grid">' + items.map(function(c) { return cardTile(c, healthCard(c)); }).join('') + '</div>'
      + '</div>';
  });

  el.innerHTML = html;
  applyCardFilters('health');
}

// ---------------------------------------------------------------------
// Library (Fas 7) - two things bundled under one nav entry, matching the
// spec's information architecture: browsing (search artists, drill into
// an artist's albums/tracks; artwork overrides CRUD) ported from the
// classic library.html/overrides.html pages onto this shell's own
// endpoints (/api/library/*, /api/overrides*, unchanged), plus the six
// library-category flat-section settings components (cache/history/
// library/overrides/posters/mediadata) via the same componentCard() used
// by every other category section - those were already fully editable
// via #component/<id> since Fas 4, they just weren't reachable from an
// in-shell Library page yet.
//
// Search results and the overrides list/settings cards each live in
// their own sub-panel (own element id) so adding an override, removing
// one, or a 15s poll tick can refresh just that panel without wiping
// out whatever's mid-typing in the search box - same reasoning as
// Health/Media/Metadata/Appearance/Displays' applyCardFilters() split
// (Fas 6/8), just three panels instead of one.
// ---------------------------------------------------------------------
var libraryQuery = '';
var librarySearchResults = null; // null = no search yet, [] = no matches
var librarySearchTimer = null;
var libraryStats = null;
var overridesData = null; // { enabled, items: [{title, subtitle, filename}] }

function libraryPageHtml() {
  return '<h1>Library</h1><p class="lede">Browse your music library, manage artwork overrides, and tune library-related settings.</p>'
    + '<div class="card">'
    + '<h2 class="group-title">Browse</h2>'
    + '<div id="library-stats" class="field-help">Loading…</div>'
    + '<input type="text" id="library-search" class="filter-search-input" placeholder="Search artists…" aria-label="Search library artists" '
    + 'value="' + esc(libraryQuery) + '" oninput="onLibrarySearchInput(this.value)" style="margin-top:8px;">'
    + '<div id="library-search-results" class="component-list" style="margin-top:12px;"></div>'
    + '</div>'
    + '<div class="card">'
    + '<h2 class="group-title">Artwork overrides</h2>'
    + '<p class="field-help">Pin a specific image for a title/subtitle that never gets a good poster from any '
    + 'enricher - matched by exact title + subtitle (e.g. movie title, or song title + artist), case-insensitive.</p>'
    + '<div id="library-overrides-panel">Loading…</div>'
    + '</div>'
    + '<div id="library-settings-cards"></div>'
    + '<p class="field-help">Prefer the classic pages? <a href="' + API_PREFIX + '/library">Library</a> &middot; <a href="' + API_PREFIX + '/overrides">Overrides</a></p>';
}

function renderLibrarySection(param) {
  var el = document.getElementById('section-library');
  if (param && param.indexOf('artist/') === 0) {
    renderLibraryArtistDetail(param.slice('artist/'.length));
    return;
  }
  if (document.getElementById('library-search')) {
    // The list view is already showing (e.g. renderFromHash() landing a
    // second time shortly after navigation, once the page's own initial
    // Promise.all(...).then(renderFromHash) resolves - or simply
    // navigating back here from another section without ever visiting the
    // artist-detail view in between). Rebuilding the whole section here
    // would tear down and recreate the search <input>, silently discarding
    // whatever the user is mid-typing. Nothing here can have gone stale
    // except the settings cards, so just refresh those - same idea as the
    // poll-tick path below.
    renderLibrarySettingsCards();
    return;
  }
  el.innerHTML = libraryPageHtml();
  renderLibrarySearchResults();
  renderLibrarySettingsCards();
  if (libraryStats) renderLibraryStats(); else fetchLibraryStats();
  if (overridesData) renderOverridesPanel(); else fetchOverrides();
}

function renderLibrarySettingsCards() {
  var el = document.getElementById('library-settings-cards');
  if (!el) return; // artist-detail sub-view is open right now, not the list
  if (!componentsData) { el.innerHTML = ''; return; }
  var items = componentsData.filter(function(c) { return c.category === 'library'; });
  if (!items.length) { el.innerHTML = ''; return; }
  el.innerHTML = '<h2 class="group-title">Settings</h2><div class="component-list">' + items.map(componentCard).join('') + '</div>';
}

// ---------------------------------------------------------------------
// Browse: search + artist detail
// ---------------------------------------------------------------------
function libraryArtistCard(a) {
  return '<a class="component-card" href="#library/artist/' + esc(a.id) + '"><div class="body"><div class="name">' + esc(a.name) + '</div></div></a>';
}

function renderLibrarySearchResults() {
  var el = document.getElementById('library-search-results');
  if (!el) return;
  if (librarySearchResults === null) el.innerHTML = '';
  else if (librarySearchResults.length === 0) el.innerHTML = '<span class="field-help">No matching artists.</span>';
  else el.innerHTML = librarySearchResults.map(libraryArtistCard).join('');
}

function onLibrarySearchInput(value) {
  libraryQuery = value;
  clearTimeout(librarySearchTimer);
  var q = value.trim();
  if (!q) {
    librarySearchResults = null;
    renderLibrarySearchResults();
    return;
  }
  librarySearchTimer = setTimeout(function() {
    apiFetch('/api/library/search?q=' + encodeURIComponent(q)).then(function(r) { return r.json(); }).then(function(data) {
      librarySearchResults = data;
      renderLibrarySearchResults();
    }).catch(function() {});
  }, 200);
}

function renderLibraryStats() {
  var el = document.getElementById('library-stats');
  if (!el || !libraryStats) return;
  el.textContent = libraryStats.artists + ' artist(s), ' + libraryStats.albums + ' album(s), ' + libraryStats.tracks + ' track(s)';
}

function fetchLibraryStats() {
  apiFetch('/api/library/stats').then(function(r) { return r.json(); }).then(function(data) {
    libraryStats = data;
    renderLibraryStats();
  }).catch(function() {});
}

function renderMbid(mbid) {
  return mbid ? '<span class="mbid">' + esc(mbid) + '</span>' : '<span class="no-mbid">no mbid</span>';
}

function libraryDetailListItems(rows) {
  if (!rows.length) return '<li>None</li>';
  return rows.map(function(row) { return '<li>' + esc(row.title) + ' &mdash; ' + renderMbid(row.mbid) + '</li>'; }).join('');
}

function renderLibraryArtistDetail(id) {
  var el = document.getElementById('section-library');
  var backLink = '<a class="back-link" href="#library">← Back to Library</a>';
  el.innerHTML = backLink + '<h1>Artist</h1><p class="lede">Loading…</p>';
  apiFetch('/api/library/artist/' + encodeURIComponent(id)).then(function(r) { return r.json(); }).then(function(a) {
    if (a.error) {
      el.innerHTML = backLink + '<h1>Artist</h1><p class="lede">' + esc(a.error) + '</p>';
      return;
    }
    el.innerHTML = backLink
      + '<h1>' + esc(a.name) + '</h1><p class="lede">' + renderMbid(a.mbid) + '</p>'
      + '<h2 class="group-title">Albums (' + a.albums.length + ')</h2>'
      + '<div class="card"><ul class="detail-list">' + libraryDetailListItems(a.albums) + '</ul></div>'
      + '<h2 class="group-title">Tracks (' + a.tracks.length + ')</h2>'
      + '<div class="card"><ul class="detail-list">' + libraryDetailListItems(a.tracks) + '</ul></div>';
  }).catch(function() {
    el.innerHTML = backLink + '<h1>Artist</h1><p class="lede">Failed to load.</p>';
  });
}

// ---------------------------------------------------------------------
// Artwork overrides: list + add/remove, same wire contract as the
// classic overrides.html (multipart POST, JSON-body DELETE).
// ---------------------------------------------------------------------
function fetchOverrides() {
  apiFetch('/api/overrides').then(function(r) { return r.json(); }).then(function(data) {
    overridesData = data;
    renderOverridesPanel();
  }).catch(function() {});
}

function overrideCard(item) {
  return '<div class="override-card">'
    + '<img src="' + API_PREFIX + '/api/overrides/image/' + encodeURIComponent(item.filename) + '" alt="">'
    + '<div class="info"><div class="title">' + esc(item.title) + '</div>'
    + '<div class="subtitle">' + esc(item.subtitle || '(no subtitle)') + '</div></div>'
    + '<button type="button" class="btn danger small" data-title="' + esc(item.title) + '" data-subtitle="' + esc(item.subtitle || '') + '" '
    + 'onclick="removeOverride(this)">Remove</button>'
    + '</div>';
}

function renderOverridesPanel() {
  var el = document.getElementById('library-overrides-panel');
  if (!el || !overridesData) return;
  var html = '';
  if (overridesData.enabled === false) {
    html += '<div class="warning-item">Overrides are disabled - enable it in the Settings cards below to turn this on.</div>';
  } else {
    html += '<form id="override-add-form" onsubmit="submitOverrideForm(event)">'
      + '<div class="field"><div class="field-row"><div class="field-label">Title</div>'
      + '<div class="field-control"><input type="text" name="title" required></div></div></div>'
      + '<div class="field"><div class="field-row"><div class="field-label">Subtitle</div>'
      + '<div class="field-control"><input type="text" name="subtitle">'
      + '<div class="field-help">Artist, episode label, etc. - leave blank if not applicable.</div></div></div></div>'
      + '<div class="field"><div class="field-row"><div class="field-label">Image file</div>'
      + '<div class="field-control"><input type="file" name="file" accept="image/*" required></div></div></div>'
      + '<div style="margin-top:10px;"><button type="submit" class="btn small">Save override</button> '
      + '<span id="override-form-status" class="field-help"></span></div>'
      + '</form>';
  }
  var items = overridesData.items || [];
  html += '<div class="override-list" style="margin-top:14px;">'
    + (items.length ? items.map(overrideCard).join('') : '<span class="field-help">No overrides yet.</span>')
    + '</div>';
  el.innerHTML = html;
}

function submitOverrideForm(e) {
  e.preventDefault();
  var form = e.target;
  var statusEl = document.getElementById('override-form-status');
  statusEl.textContent = 'Saving…';
  apiFetch('/api/overrides', { method: 'POST', headers: CSRF_HEADERS, body: new FormData(form) })
    .then(function(r) { return r.json().then(function(data) { return [r.ok, data]; }); })
    .then(function(result) {
      if (result[0]) { form.reset(); fetchOverrides(); }
      else statusEl.textContent = result[1].error || 'Failed to save override.';
    })
    .catch(function() { statusEl.textContent = 'Request failed.'; });
}

function removeOverride(btn) {
  btn.disabled = true;
  apiFetch('/api/overrides', {
    method: 'DELETE',
    headers: Object.assign({ 'Content-Type': 'application/json' }, CSRF_HEADERS),
    body: JSON.stringify({ title: btn.dataset.title, subtitle: btn.dataset.subtitle }),
  }).then(function() { fetchOverrides(); }).catch(function() { btn.disabled = false; });
}
