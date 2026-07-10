'use strict';

// Dashboard shell (Fas 2-8 of the GUI redesign) - the new landing page at
// "/". Dashboard/Pipeline/Media/Metadata/Appearance/Displays/Library/
// Health are all rendered in-shell via hash-based client routing (see
// renderFromHash() below); Advanced stays a plain <a href> link straight
// into the classic shell (see templates/config_ui/dashboard.html), since
// raw YAML/backups/etc. don't have (or need) an in-shell equivalent yet.
//
// This file owns the shell chrome (nav/theme/routing) plus Dashboard and
// Pipeline. Media/Metadata/Appearance/Displays' card-grid rendering
// (filterable + hideable since Fas 8), Health's action-oriented card grid
// (Fas 6/8), Library's browse/overrides/settings page (Fas 7), and the
// per-component detail page (essential/advanced fields, save/discard/
// test-connection - Fas 4) live in components.js, loaded after this file
// and sharing its esc()/theme helpers, componentsData/componentsById, and
// the confirmDiscardIfDirty() guard via the hasUnsavedComponentEdits flag
// below.
//
// This file only ever reads from the read-only /api/ui/* endpoints
// (Fas 1); components.js is the one file that writes, via the exact same
// /api/config/form, /api/test/*, /api/library/*, /api/overrides*, and
// /api/restart endpoints the classic shell already uses - no new backend
// surface anywhere in this redesign.

var CATEGORY_SECTIONS = ['media', 'metadata', 'appearance', 'displays'];
// The five sections with a card-grid + filter bar + per-card hide (Fas 8) -
// see components.js's cardTile()/applyCardFilters()/filterBarHtml(). Library
// deliberately isn't included: it reuses componentCard()/.component-list
// for its settings cards, but stays plain - no grid, no hide, no filter.
var FILTERABLE_SECTIONS = CATEGORY_SECTIONS.concat(['health']);
var NAV_SECTIONS = ['dashboard', 'pipeline'].concat(CATEGORY_SECTIONS, ['library', 'health']);
var SECTION_TITLES = {
  dashboard: 'Dashboard', pipeline: 'Pipeline', media: 'Media',
  metadata: 'Metadata', appearance: 'Appearance', displays: 'Displays',
  library: 'Library', health: 'Health',
};
// UiComponent.category uses "display" (singular); the nav/section id uses
// "displays" - this is the one place that mapping happens. "library"
// matches its section id directly, but still needs an explicit entry
// here so a library-category component's detail page ("← Back to
// Library" link, nav highlight) doesn't fall back to "dashboard".
var CATEGORY_TO_SECTION = { media: 'media', metadata: 'metadata', appearance: 'appearance', display: 'displays', library: 'library' };

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
  var section = (NAV_SECTIONS.indexOf(parts[0]) !== -1 || parts[0] === 'component') ? parts[0] : 'dashboard';
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
  else if (name === 'health') renderHealthSection();
  else if (name === 'component') renderComponentDetail(param);
}

// ---------------------------------------------------------------------
// Dashboard section
// ---------------------------------------------------------------------
var STATUS_LABELS = {
  connected: 'Connected', enabled: 'Enabled', disabled: 'Disabled',
  needs_configuration: 'Needs configuration', error: 'Error', unknown: 'Unknown',
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
  fetch(href, { method: 'POST' }).catch(function() {});
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
    + (d.quick_actions || []).map(actionButton).join('') + '</div>';

  html += '</div>';
  el.innerHTML = html;
}

function fetchDashboard() {
  return fetch('/api/ui/dashboard').then(function(r) { return r.json(); }).then(function(data) {
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
    + '<p class="lede">What’s currently enabled at each stage of the media flow - read-only for now, reordering is a future phase.</p>';
  html += '<div class="card"><div class="pipeline-grid">' + PIPELINE_STAGES.map(function(stage) {
    return pipelineStage(stage.label, pipeline[stage.key] || []);
  }).join('') + '</div></div>';

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
  return fetch('/api/ui/pipelines').then(function(r) { return r.json(); }).then(function(data) {
    pipelineData = data;
    if (currentSection === 'pipeline') renderPipeline();
  }).catch(function() {});
}

function fetchComponents() {
  return fetch('/api/ui/components').then(function(r) { return r.json(); }).then(function(data) {
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
  if (currentSection === 'pipeline') { fetchPipeline(); fetchComponents(); }
  else if (currentSection === 'health' || currentSection === 'library' || CATEGORY_SECTIONS.indexOf(currentSection) !== -1) { fetchComponents(); }
}, 15000);

Promise.all([fetchDashboard(), fetchPipeline(), fetchComponents()]).then(renderFromHash);
