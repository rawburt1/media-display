'use strict';

// Dashboard shell (Fas 2-3 of the GUI redesign) - the new landing page at
// "/". Only two nav entries are rendered by this file (Dashboard,
// Pipeline); every other nav entry is a plain <a href> straight into the
// classic shell (see templates/config_ui/dashboard.html) since their real
// in-shell pages don't exist yet (Media/Metadata/Appearance/Displays:
// Fas 4). Pipeline (Fas 3) is a *read-only* visual flow of the currently
// enabled components (Media -> Metadata -> Appearance -> Displays, plus a
// separate idle-fallback row) - no reordering/editing, just a nicer view
// of the same /api/ui/pipelines + /api/ui/components data. This file only
// ever reads from the read-only /api/ui/* endpoints (Fas 1) plus the two
// POST endpoints (/api/restart, /api/test/source/<name>) that already
// existed before Fas 2 - no new write path is introduced here.

var NAV_TITLES = { dashboard: 'Dashboard', pipeline: 'Pipeline' };
var currentSection = 'dashboard';
var dashboardData = null;
var pipelineData = null;
var componentsData = null;
var componentsById = {};

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
// Navigation between the two JS-rendered sections
// ---------------------------------------------------------------------
function goToSection(name) {
  currentSection = name;
  location.hash = name;
  document.querySelectorAll('#nav button[data-section]').forEach(function(b) {
    b.classList.toggle('active', b.dataset.section === name);
  });
  document.querySelectorAll('.section').forEach(function(s) {
    s.classList.toggle('active', s.id === 'section-' + name);
  });
  document.getElementById('topbar-title').textContent = NAV_TITLES[name] || '';
  if (document.body.classList.contains('nav-open')) closeNav();
  renderSection(name);
}
document.getElementById('nav').addEventListener('click', function(e) {
  var btn = e.target.closest('button[data-section]');
  if (btn) goToSection(btn.dataset.section);
});

function renderSection(name) {
  if (name === 'dashboard') renderDashboard();
  else if (name === 'pipeline') renderPipeline();
}

// ---------------------------------------------------------------------
// Dashboard section
// ---------------------------------------------------------------------
var STATUS_LABELS = {
  connected: 'Connected', enabled: 'Enabled', disabled: 'Disabled',
  needs_configuration: 'Needs configuration', error: 'Error', unknown: 'Unknown',
};

function statTile(num, label, statusClass) {
  return '<div class="stat-card"><div class="stat-num">' + num + '</div>'
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

  html += '<div class="card">';
  if (np) {
    html += '<div class="now-playing"><div>'
      + '<div class="title">' + esc(np.title) + '</div>'
      + (np.subtitle ? '<div class="subtitle">' + esc(np.subtitle) + '</div>' : '')
      + '<div class="subtitle">via ' + esc(d.active_source || np.source) + ' · ' + esc(np.media_type) + '</div>'
      + '</div></div>';
  } else {
    html += '<div class="now-playing"><span class="subtitle">Nothing is playing right now.</span></div>';
  }
  html += '</div>';

  var counts = (d.health && d.health.counts_by_status) || {};
  html += '<div class="stat-grid">' + Object.keys(counts).map(function(status) {
    return statTile(counts[status], STATUS_LABELS[status] || status, 'b-' + status);
  }).join('') + '</div>';

  html += '<h2 class="group-title">Needs attention</h2>';
  var warnings = (d.health && d.health.warnings) || [];
  if (warnings.length === 0) {
    html += '<div class="card"><span style="color:var(--ok);font-size:13px;">Everything looks good.</span></div>';
  } else {
    html += '<ul class="warning-list">' + warnings.map(function(w) {
      return '<li class="warning-item">' + esc(w) + '</li>';
    }).join('') + '</ul>';
  }

  html += '<div class="action-row">' + (d.quick_actions || []).map(actionButton).join('') + '</div>';

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
// status badge + first warning, rendered as a clickable card.
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
  var href = (c.actions && c.actions[0] && c.actions[0].href) || '/form';
  return '<a class="pipeline-card" href="' + esc(href) + '">'
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
  }).catch(function() {});
}

// ---------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------
setInterval(function() {
  fetchDashboard();
  if (currentSection === 'pipeline') { fetchPipeline(); fetchComponents(); }
}, 15000);

Promise.all([fetchDashboard(), fetchPipeline(), fetchComponents()]).then(function() {
  var hash = location.hash.replace('#', '');
  goToSection(hash && NAV_TITLES[hash] ? hash : 'dashboard');
});
