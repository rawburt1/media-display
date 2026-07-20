'use strict';

// Dashboard shell (Fas 2-8 of the GUI redesign, H5's single-shell finish
// line) - the only landing page at "/" now that the classic app.html
// shell is gone. Dashboard/Pipeline/Media/Metadata/Appearance/Displays/
// Library/Health/Advanced are all rendered in-shell via hash-based client
// routing (see renderFromHash() below).
//
// This file owns the shell chrome (nav/theme/routing/Hitster-safe) plus
// Dashboard and Pipeline. Media/Metadata/Appearance/Displays' card-grid
// rendering (filterable + hideable since Fas 8), Health's action-oriented
// card grid (Fas 6/8), Library's browse/overrides/settings page (Fas 7),
// and the per-component detail page (essential/advanced fields, save/
// discard/test-connection - Fas 4) live in components.js, loaded after
// this file and sharing its esc()/theme helpers, componentsData/
// componentsById, and the confirmDiscardIfDirty() guard via the
// hasUnsavedComponentEdits flag below. Advanced (settings cards, config
// backups/download, raw YAML editor) lives in advanced.js, loaded last.
//
// This file only ever reads from the read-only /api/ui/* endpoints
// (Fas 1); components.js and advanced.js are what write, via
// /api/config/form, /api/config/raw, /api/config/backups(/restore),
// /api/test/*, /api/library/*, /api/overrides*, and /api/restart - the
// same backend surface the classic shell always used, no new endpoints
// added anywhere in this redesign.

var CATEGORY_SECTIONS = ['media', 'metadata', 'appearance', 'displays'];
// The five sections with a card-grid + filter bar + per-card hide (Fas 8) -
// see components.js's cardTile()/applyCardFilters()/filterBarHtml(). Library
// deliberately isn't included: it reuses componentCard()/.component-list
// for its settings cards, but stays plain - no grid, no hide, no filter.
var FILTERABLE_SECTIONS = CATEGORY_SECTIONS.concat(['health']);
var NAV_SECTIONS = ['dashboard', 'pipeline'].concat(CATEGORY_SECTIONS, ['library', 'history', 'health', 'advanced']);
var SECTION_TITLES = {
  dashboard: 'Dashboard', pipeline: 'Pipeline', media: 'Media',
  metadata: 'Metadata', appearance: 'Appearance', displays: 'Displays',
  library: 'Library', history: 'History', health: 'Health', advanced: 'Advanced', wizard: 'Setup',
};
// UiComponent.category uses "display" (singular); the nav/section id uses
// "displays" - this is the one place that mapping happens. "library"/
// "advanced" match their section id directly, but still need an explicit
// entry here so a library- or advanced-category component's detail page
// ("← Back to X" link, nav highlight) doesn't fall back to "dashboard".
var CATEGORY_TO_SECTION = { media: 'media', metadata: 'metadata', appearance: 'appearance', display: 'displays', library: 'library', advanced: 'advanced' };

var currentSection = 'dashboard';
var currentParam = null;
var dashboardData = null;
var pipelineData = null;
var componentsData = null;
var componentsById = {};

// Set by components.js while a component detail page has local, unsaved
// edits - guards in-app navigation (confirmDiscardIfDirty(), below) and a
// real page unload/close (beforeunload, below).
var hasUnsavedComponentEdits = false;

// Every state-changing fetch() (POST/PUT/PATCH/DELETE) in this file and
// components.js must send this - see mediainfo/web_auth.py's
// _require_csrf_header for why: a cross-origin page can't set this header
// without triggering a CORS preflight this app never grants, and a plain
// <form> POST can't set custom headers at all. Not needed on GETs.
var CSRF_HEADERS = { 'X-Requested-With': 'XMLHttpRequest' };

// window.API_PREFIX is set by a small inline <script> in dashboard.html,
// before this file loads (see config_ui.py's build_http_blueprint()) - the
// path this instance is mounted at (e.g. "/config", or "" at the root).
// Every fetch() in this file and components.js/wizard.js that targets one
// of this output's own routes must go through this, not a bare fetch(),
// now that routes aren't guaranteed to be unprefixed - see H1 in
// docs/architecture-usability-review-2026-07.md.
var API_PREFIX = window.API_PREFIX || '';
function apiFetch(url, opts) { return fetch(API_PREFIX + url, opts); }

function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------
// Theme (shared with the classic shell via the same localStorage key)
// ---------------------------------------------------------------------
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('mediainfo-theme', theme);
  var btn = document.getElementById('theme-toggle');
  btn.textContent = theme === 'light' ? 'Theme: light' : 'Theme: dark';
  btn.setAttribute('aria-pressed', String(theme === 'light'));
}
function toggleTheme() {
  var current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  applyTheme(current === 'light' ? 'dark' : 'light');
}
applyTheme(localStorage.getItem('mediainfo-theme') || 'dark');

// ---------------------------------------------------------------------
// Hitster-safe (ported as-is from the classic shell)
// ---------------------------------------------------------------------
var hitsterSafeEnabled = false;
function renderHitsterSafeButton() {
  var btn = document.getElementById('hitster-safe-btn');
  btn.textContent = hitsterSafeEnabled ? 'Hitster-safe: ON' : 'Hitster-safe';
  btn.classList.toggle('active', hitsterSafeEnabled);
  btn.setAttribute('aria-pressed', String(hitsterSafeEnabled));
}
function toggleHitsterSafe() {
  apiFetch('/api/hitster-safe', {
    method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, CSRF_HEADERS),
    body: JSON.stringify({ enabled: !hitsterSafeEnabled }),
  }).then(function(r) { return r.json(); })
    .then(function(d) { hitsterSafeEnabled = !!d.enabled; renderHitsterSafeButton(); })
    .catch(function() {});
}
apiFetch('/api/hitster-safe').then(function(r) { return r.json(); })
  .then(function(d) { hitsterSafeEnabled = !!d.enabled; renderHitsterSafeButton(); }).catch(function() {});

// ---------------------------------------------------------------------
// Mobile nav drawer
// ---------------------------------------------------------------------
function openNav() {
  document.body.classList.add('nav-open');
  document.getElementById('hamburger').setAttribute('aria-expanded', 'true');
}
function closeNav() {
  document.body.classList.remove('nav-open');
  document.getElementById('hamburger').setAttribute('aria-expanded', 'false');
}
function toggleNav() {
  if (document.body.classList.contains('nav-open')) closeNav(); else openNav();
}

// ---------------------------------------------------------------------
// Hash-based routing - a single source of truth (renderFromHash, driven
// by the hashchange event) instead of separate click-time and init-time
// render paths, so back/forward and typed-in hashes all work the same way.
// Supports a dynamic second segment for component detail pages, e.g.
// "#component/sources.kodi".
// ---------------------------------------------------------------------
function confirmDiscardIfDirty() {
  if (!hasUnsavedComponentEdits) return true;
  if (!confirm('Discard unsaved changes?')) return false;
  hasUnsavedComponentEdits = false;
  return true;
}

function parseHash() {
  var raw = location.hash.replace('#', '');
  var parts = raw.split('/');
  var section = (NAV_SECTIONS.indexOf(parts[0]) !== -1 || parts[0] === 'component' || parts[0] === 'wizard') ? parts[0] : 'dashboard';
  var param = parts.slice(1).join('/') || null;
  return { section: section, param: param };
}

function setActiveNav(name) {
  document.querySelectorAll('#nav button[data-section]').forEach(function(b) {
    b.classList.toggle('active', b.dataset.section === name);
  });
}

function renderFromHash() {
  var parsed = parseHash();
  currentSection = parsed.section;
  currentParam = parsed.param;
  // A component detail page highlights whichever category nav button it
  // belongs to (set by renderComponentDetail() once it knows the
  // component) rather than a dedicated "component" nav entry, which
  // doesn't exist.
  if (currentSection !== 'component') setActiveNav(currentSection);
  document.querySelectorAll('.section').forEach(function(s) {
    s.classList.toggle('active', s.id === 'section-' + currentSection);
  });
  document.getElementById('topbar-title').textContent = SECTION_TITLES[currentSection] || '';
  if (document.body.classList.contains('nav-open')) closeNav();
  renderSection(currentSection, currentParam);
}

document.getElementById('nav').addEventListener('click', function(e) {
  var btn = e.target.closest('button[data-section]');
  if (btn && confirmDiscardIfDirty()) location.hash = btn.dataset.section;
});
// Delegated guard for every in-shell "#..." link (component/list cards,
// "Back to <category>" links) - real (non-hash) links, e.g. the auth
// banner's "/form" link, are untouched.
document.getElementById('main').addEventListener('click', function(e) {
  var a = e.target.closest('a[href^="#"]');
  if (a && !confirmDiscardIfDirty()) e.preventDefault();
});
window.addEventListener('hashchange', renderFromHash);
window.addEventListener('beforeunload', function(e) {
  if (hasUnsavedComponentEdits) { e.preventDefault(); e.returnValue = ''; }
});

function renderSection(name, param) {
  if (name === 'dashboard') renderDashboard();
  else if (name === 'pipeline') renderPipeline();
  else if (CATEGORY_SECTIONS.indexOf(name) !== -1) renderCategorySection(name);
  else if (name === 'library') renderLibrarySection(param);
  else if (name === 'history') renderHistorySection();
  else if (name === 'health') renderHealthSection();
  else if (name === 'advanced') renderAdvancedSection();
  else if (name === 'component') renderComponentDetail(param);
  else if (name === 'wizard') renderWizard();
}

// ---------------------------------------------------------------------
// Dashboard section
// ---------------------------------------------------------------------
var STATUS_LABELS = {
  connected: 'Connected', enabled: 'Enabled', disabled: 'Disabled',
  needs_configuration: 'Needs configuration', warning: 'Warning', error: 'Error', unknown: 'Unknown',
};

// Activity (Fas 10) is a separate concept from the status badges above -
// what a source is doing right now, never a failure signal on its own
// (see mediainfo.status.Activity). Used for the Dashboard's aggregate
// counts below and, per-card, by components.js's healthCard(). The card-
// level label text itself comes from the backend (activity_label) so it
// stays in sync with mediainfo.status's translation table; this map is
// just the CSS class per value for the Dashboard's own aggregate tiles.
var ACTIVITY_LABELS = {
  playing: 'Playing', paused: 'Paused', idle: 'Idle', sleeping: 'Sleeping', unknown: 'Unknown',
};
var ACTIVITY_LABEL_CLASS = {
  playing: 'a-playing', paused: 'a-paused', idle: 'a-idle', sleeping: 'a-sleeping', unknown: 'a-unknown',
};

function bentoStatItem(num, label, statusClass) {
  return '<div class="bento-item bento-item--stat"><div class="stat-num">' + num + '</div>'
    + '<div class="stat-label"><span class="badge ' + (statusClass || '') + '">' + esc(label) + '</span></div></div>';
}

function actionButton(action) {
  if (action.kind === 'restart') {
    return '<button type="button" class="btn danger" onclick="runRestartAction(\'' + esc(action.href) + '\')">' + esc(action.label) + '</button>';
  }
  return '<a class="btn secondary" href="' + esc(action.href || '#') + '">' + esc(action.label) + '</a>';
}

function runRestartAction(href) {
  if (!confirm('Restart mediainfo now? Every display goes offline until it comes back up.')) return;
  apiFetch(href, { method: 'POST', headers: CSRF_HEADERS }).catch(function() {});
  alert('Restarting… this page will keep working once the process is back up (if something supervises it, e.g. Docker’s restart: unless-stopped).');
  fetchDashboard();
}

function renderDashboard() {
  var el = document.getElementById('section-dashboard');
  if (!dashboardData) {
    el.innerHTML = '<h1>Dashboard</h1><p class="lede">Loading…</p>';
    return;
  }
  var d = dashboardData;
  var np = d.now_playing;

  var html = '<h1>Dashboard</h1><p class="lede">A quick look at what mediainfo is doing right now, and anything that needs your attention.</p>';
  html += '<div class="bento-grid">';

  html += '<div class="bento-item bento-item--now-playing">';
  if (np) {
    html += '<div class="eyebrow">Now playing' + (d.active_source ? ' · ' + esc(d.active_source) : '') + '</div>'
      + '<div class="title">' + esc(np.title) + '</div>'
      + (np.subtitle ? '<div class="subtitle">' + esc(np.subtitle) + '</div>' : '')
      + (np.media_type ? '<div class="subtitle">' + esc(np.media_type) + '</div>' : '');
  } else {
    html += '<div class="eyebrow">Now playing</div><div class="subtitle">Nothing is playing right now.</div>';
  }
  html += '</div>';

  var activity = d.activity_summary || {};
  html += Object.keys(activity).map(function(a) {
    return bentoStatItem(activity[a], ACTIVITY_LABELS[a] || a, ACTIVITY_LABEL_CLASS[a] || '');
  }).join('');

  var counts = (d.health && d.health.counts_by_status) || {};
  html += Object.keys(counts).map(function(status) {
    return bentoStatItem(counts[status], STATUS_LABELS[status] || status, 'b-' + status);
  }).join('');

  var warnings = (d.health && d.health.warnings) || [];
  html += '<div class="bento-item bento-item--warnings">';
  if (warnings.length === 0) {
    html += '<div class="row"><span>Everything looks good</span><span class="badge b-connected">Healthy</span></div>';
  } else {
    html += warnings.map(function(w) {
      return '<div class="row"><span>' + esc(w) + '</span><span class="badge b-needs_configuration">Action needed</span></div>';
    }).join('');
  }
  html += '</div>';

  html += '<div class="bento-item bento-item--actions">'
    + '<a class="btn secondary" href="#wizard">Run setup wizard</a>'
    + (d.quick_actions || []).map(actionButton).join('') + '</div>';

  html += '</div>';
  el.innerHTML = html;
}

function fetchDashboard() {
  return apiFetch('/api/ui/dashboard').then(function(r) { return r.json(); }).then(function(data) {
    dashboardData = data;
    if (currentSection === 'dashboard') renderDashboard();
  }).catch(function() {});
}

// ---------------------------------------------------------------------
// Pipeline section - read-only visual flow of currently enabled
// components (Fas 3). No reordering/editing: just /api/ui/pipelines'
// bucketed ids, each looked up against /api/ui/components for a name +
// status badge + first warning, rendered as a clickable card that opens
// that component's new detail page (Fas 4).
// ---------------------------------------------------------------------
var PIPELINE_STAGES = [
  { key: 'media_component_ids', label: 'Media' },
  { key: 'metadata_component_ids', label: 'Metadata' },
  { key: 'appearance_component_ids', label: 'Appearance' },
  { key: 'display_component_ids', label: 'Displays' },
];

function pipelineCard(id) {
  var c = componentsById[id];
  if (!c) return '<div class="pipeline-card"><div class="name">' + esc(id) + '</div></div>';
  var warning = c.warnings && c.warnings.length ? '<div class="warning">' + esc(c.warnings[0]) + '</div>' : '';
  return '<a class="pipeline-card" href="#component/' + esc(c.id) + '">'
    + '<div class="name">' + esc(c.name) + '</div>'
    + '<span class="badge b-' + esc(c.status) + '">' + esc(STATUS_LABELS[c.status] || c.status) + '</span>'
    + warning
    + '</a>';
}

function pipelineStage(label, ids) {
  var body = ids.length
    ? ids.map(pipelineCard).join('')
    : '<div class="pipeline-stage-empty">None enabled</div>';
  return '<div class="pipeline-stage"><h3>' + esc(label) + '</h3>' + body + '</div>';
}

function renderPipeline() {
  var el = document.getElementById('section-pipeline');
  if (!pipelineData || !componentsData) {
    el.innerHTML = '<h1>Pipeline</h1><p class="lede">Loading…</p>';
    return;
  }
  var pipeline = pipelineData[0] || {};
  var html = '<h1>Pipeline</h1>'
    + '<p class="lede">What’s currently enabled at each stage of the media flow.</p>';
  html += '<div class="card"><div class="pipeline-grid">' + PIPELINE_STAGES.map(function(stage) {
    return pipelineStage(stage.label, pipeline[stage.key] || []);
  }).join('') + '</div></div>';

  if (priorityWorking) {
    html += '<h2 class="group-title">Timing &amp; priority</h2>';
    html += renderPriorityList(
      'source', 'general.priority',
      'Source priority',
      'When more than one source is active at once, the highest one in this list wins. A source you enable above but don’t add here is simply never used.',
      'sources'
    );
    html += renderPriorityList(
      'idle_source', 'general.idle_priority',
      'Idle screen priority',
      'When nothing is playing, the highest enabled idle source in this list is shown.',
      'idle sources'
    );
    html += '<div class="action-row">'
      + '<button type="button" class="btn secondary" onclick="discardPriorityEdits()">Discard</button>'
      + '<button type="button" class="btn" onclick="savePriorityLists()">Save</button>'
      + '</div>'
      + '<div id="priority-save-status" style="margin-top:8px;font-size:12.5px;"></div>';
  }

  var idleIds = componentsData
    .filter(function(c) { return c.component_type === 'idle_source' && c.enabled; })
    .map(function(c) { return c.id; });
  if (idleIds.length) {
    html += '<h2 class="group-title">When nothing is playing</h2>';
    html += '<div class="card"><div class="pipeline-idle-row">' + idleIds.map(pipelineCard).join('') + '</div></div>';
  }

  el.innerHTML = html;
}

function fetchPipeline() {
  return apiFetch('/api/ui/pipelines').then(function(r) { return r.json(); }).then(function(data) {
    pipelineData = data;
    if (currentSection === 'pipeline') renderPipeline();
  }).catch(function() {});
}

// ---------------------------------------------------------------------
// Pipeline section: source/idle priority reordering (H5 M5) - the one
// piece of Pipeline that's actually editable. There's no single
// component id to hang this off (it's two top-level config.yaml keys,
// not one plugin's settings), so it gets its own small save/discard pair
// instead of components.js's per-component one - but saves through the
// exact same /api/config/form "values" path
// ({"general.priority": [...], "general.idle_priority": [...]}), and
// reuses the same hasUnsavedComponentEdits dirty flag so navigating away
// or closing the tab mid-edit is guarded the same way a component
// detail page's edits are.
// ---------------------------------------------------------------------
var priorityWorking = null; // {"general.priority": [...], "general.idle_priority": [...]} once loaded

function fetchPriorityLists() {
  if (hasUnsavedComponentEdits) return Promise.resolve(); // don't clobber an in-progress edit on a poll tick
  return apiFetch('/api/config').then(function(r) { return r.json(); }).then(function(cfg) {
    var values = cfg.values || {};
    priorityWorking = {
      'general.priority': values['general.priority'] || [],
      'general.idle_priority': values['general.idle_priority'] || [],
    };
  }).catch(function() {});
}

function priorityAllNames(componentType) {
  return componentsData.filter(function(c) { return c.component_type === componentType; })
    .map(function(c) { return c.id.split('.')[1]; });
}

function priorityComponent(componentType, name) {
  return componentsById[(componentType === 'source' ? 'sources.' : 'idle.') + name];
}

var _priorityDragName = null;
function priorityDragStart(name) { _priorityDragName = name; }
function priorityDragOver(e) { e.preventDefault(); }
function priorityDrop(e, key, targetName) {
  e.preventDefault();
  if (!_priorityDragName || _priorityDragName === targetName) return;
  var list = priorityWorking[key];
  var from = list.indexOf(_priorityDragName);
  var to = list.indexOf(targetName);
  _priorityDragName = null;
  if (from === -1 || to === -1) return;
  list.splice(from, 1);
  list.splice(to, 0, _priorityDragName);
  hasUnsavedComponentEdits = true;
  renderPipeline();
}
function priorityMove(key, name, delta) {
  var list = priorityWorking[key];
  var i = list.indexOf(name);
  var j = i + delta;
  if (i === -1 || j < 0 || j >= list.length) return;
  list.splice(i, 1);
  list.splice(j, 0, name);
  hasUnsavedComponentEdits = true;
  renderPipeline();
}
function priorityRemove(key, name) {
  priorityWorking[key] = priorityWorking[key].filter(function(n) { return n !== name; });
  hasUnsavedComponentEdits = true;
  renderPipeline();
}
function priorityAdd(key, name) {
  if (priorityWorking[key].indexOf(name) === -1) priorityWorking[key].push(name);
  hasUnsavedComponentEdits = true;
  renderPipeline();
}

function renderPriorityList(componentType, key, title, help, noun) {
  var allNames = priorityAllNames(componentType);
  var order = priorityWorking[key].filter(function(n) { return allNames.indexOf(n) !== -1; });
  var missing = allNames.filter(function(n) {
    var c = priorityComponent(componentType, n);
    return order.indexOf(n) === -1 && c && c.enabled;
  });

  var html = '<div class="card"><h2 class="heading-sm">' + esc(title) + '</h2>'
    + '<p class="field-help" style="margin:6px 0 12px;">' + esc(help) + '</p>';

  if (!order.length) {
    html += '<p class="field-help">No enabled ' + esc(noun) + ' are in priority order yet.</p>';
  } else {
    html += '<ul class="order-list">' + order.map(function(name, i) {
      var c = priorityComponent(componentType, name);
      var label = c ? c.name : name;
      return '<li class="order-item" draggable="true" '
        + 'ondragstart="priorityDragStart(\'' + esc(name) + '\')" ondragover="priorityDragOver(event)" '
        + 'ondrop="priorityDrop(event,\'' + key + '\',\'' + esc(name) + '\')">'
        + '<span class="grip" aria-hidden="true">☰</span>'
        + '<span class="name">' + (i + 1) + '. ' + esc(label) + '</span>'
        + '<button type="button" aria-label="Move up" onclick="priorityMove(\'' + key + '\',\'' + esc(name) + '\',-1)"' + (i === 0 ? ' disabled' : '') + '>↑</button>'
        + '<button type="button" aria-label="Move down" onclick="priorityMove(\'' + key + '\',\'' + esc(name) + '\',1)"' + (i === order.length - 1 ? ' disabled' : '') + '>↓</button>'
        + '<button type="button" aria-label="Remove from priority" onclick="priorityRemove(\'' + key + '\',\'' + esc(name) + '\')">Remove</button>'
        + '</li>';
    }).join('') + '</ul>';
  }

  if (missing.length) {
    html += '<div class="missing-priority">' + missing.map(function(name) {
      var c = priorityComponent(componentType, name);
      var label = c ? c.name : name;
      return esc(label) + ' is enabled but not in priority - '
        + '<button type="button" class="link-btn" onclick="priorityAdd(\'' + key + '\',\'' + esc(name) + '\')">add it</button>';
    }).join('<br>') + '</div>';
  }

  html += '</div>';
  return html;
}

function savePriorityLists() {
  var statusEl = document.getElementById('priority-save-status');
  statusEl.textContent = 'Saving…';
  statusEl.className = '';
  apiFetch('/api/config/form', {
    method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, CSRF_HEADERS),
    body: JSON.stringify({ values: priorityWorking }),
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (!d.ok) {
      statusEl.textContent = d.error || 'Save failed.';
      statusEl.className = 'err';
      return;
    }
    hasUnsavedComponentEdits = false;
    fetchDashboard();
    fetchPriorityLists().then(renderPipeline).then(function() {
      var freshStatusEl = document.getElementById('priority-save-status');
      if (freshStatusEl) {
        freshStatusEl.textContent = 'Saved - changes take effect within a few seconds.';
        freshStatusEl.className = 'ok';
      }
    });
  }).catch(function() {
    statusEl.textContent = 'Request failed.';
    statusEl.className = 'err';
  });
}

function discardPriorityEdits() {
  if (!confirm('Discard unsaved changes?')) return;
  hasUnsavedComponentEdits = false;
  fetchPriorityLists().then(renderPipeline);
}

function fetchComponents() {
  return apiFetch('/api/ui/components').then(function(r) { return r.json(); }).then(function(data) {
    componentsData = data;
    componentsById = {};
    data.forEach(function(c) { componentsById[c.id] = c; });
    if (currentSection === 'pipeline') renderPipeline();
    else if (currentSection === 'library') {
      // Same reasoning as the filterable sections below, but Library's
      // settings cards are only one part of a page that also holds live
      // search/artist-detail state - refresh just that one sub-panel
      // instead of the whole section (see renderLibrarySettingsCards()).
      renderLibrarySettingsCards();
    } else if (currentSection === 'advanced') {
      // Same reasoning as Library above: only the settings cards depend on
      // componentsData - refreshing them must not touch the raw YAML
      // textarea/backups list next to them, or a poll tick would blow away
      // whatever the user is mid-typing there (see advanced.js).
      renderAdvancedSettingsCards();
    } else if (FILTERABLE_SECTIONS.indexOf(currentSection) !== -1) {
      // A full re-render would reset the search input's value/focus out
      // from under someone mid-keystroke (it happens to have focus right
      // when a 15s poll tick lands) - just re-apply the filters against
      // the freshly-fetched data instead, and let the next real render
      // (navigation, or a poll while not typing) catch up the card
      // contents themselves. See components.js's applyCardFilters().
      var active = document.activeElement;
      if (active && active.id === currentSection + '-search') applyCardFilters(currentSection);
      else if (currentSection === 'health') renderHealthSection();
      else renderCategorySection(currentSection);
    }
  }).catch(function() {});
}

// ---------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------
setInterval(function() {
  fetchDashboard();
  if (currentSection === 'pipeline') { fetchPipeline(); fetchComponents(); fetchPriorityLists().then(renderPipeline); }
  else if (currentSection === 'history') { fetchHistory(); }
  else if (currentSection === 'health' || currentSection === 'library' || currentSection === 'advanced' || CATEGORY_SECTIONS.indexOf(currentSection) !== -1) { fetchComponents(); }
}, 15000);

Promise.all([fetchDashboard(), fetchPipeline(), fetchComponents(), fetchPriorityLists()]).then(function() {
  // First-run wizard (Fas 11): a bare initial load (no hash at all - not a
  // bookmark, not back/forward navigation) with nothing configured yet goes
  // straight into the wizard instead of the empty Dashboard. needs_setup is
  // recomputed by the backend every request, so this never fires again once
  // a source and an output are both enabled. Setting location.hash fires its
  // own hashchange -> renderFromHash(), so only call it directly otherwise.
  if (dashboardData && dashboardData.needs_setup && !location.hash) {
    location.hash = 'wizard';
  } else {
    renderFromHash();
  }
});
