'use strict';

// First-run setup wizard (Fas 11) - shown automatically on a bare initial
// load when nothing is configured yet (dashboardData.needs_setup, see
// dashboard.js's init) and always reachable afterward via the Dashboard's
// "Run setup wizard" action.
//
// Deliberately thin: picking a source/output hands off to the real,
// existing #component/<id> detail page (components.js) for the actual
// field-filling/secrets/save/test-connection work - this file only
// sequences that existing page (via wizardState) and reuses componentCard()'s
// markup for the picker grids and actionButton() for the restart action, so
// there's no second field-rendering or save code path to keep in sync.

var wizardState = { active: false, step: 'welcome', returnStep: null };

var WIZARD_STEP_NUMBER = {
  welcome: 1, source: 2, 'source-detail': 2, output: 3, 'output-detail': 3, done: 4,
};

function renderWizard() {
  var el = document.getElementById('section-wizard');
  var html = '<h1>Set up mediainfo</h1>'
    + '<div class="wizard-progress">Step ' + WIZARD_STEP_NUMBER[wizardState.step] + ' of 4</div>';

  if (wizardState.step === 'source' || wizardState.step === 'output') {
    var type = wizardState.step;
    var items = (componentsData || []).filter(function(c) { return c.component_type === type; });
    html += '<p class="lede">'
      + (type === 'source' ? 'Choose a source to read what’s playing.' : 'Choose a display to show it on.')
      + ' You can add more later from ' + (type === 'source' ? 'Media' : 'Displays') + '.</p>';
    html += items.length
      ? '<div class="card-grid">' + items.map(componentCard).join('') + '</div>'
      : '<div class="card"><span class="field-help">Nothing available here yet.</span></div>';
  } else if (wizardState.step === 'done') {
    html += '<p class="lede">You’re set up. mediainfo will start showing what’s playing.</p>';
    html += '<div class="wizard-actions">'
      + (dashboardData && dashboardData.restart_required
        ? actionButton({ id: 'restart', label: 'Restart mediainfo', kind: 'restart', href: '/api/restart' })
        : '<a class="btn" href="#dashboard">Go to Dashboard</a>')
      + '</div>';
  } else if (wizardState.step === 'source-detail' || wizardState.step === 'output-detail') {
    // The hash actually points at #component/<id> during these steps (see
    // the click handler below) - this only shows if #wizard is reached
    // directly while wizardState still has a stale in-progress step.
    html += '<p class="lede">Continue in the panel that just opened.</p>';
  } else {
    html += '<p class="lede">mediainfo needs two things to get going: a source to read what’s '
      + 'playing, and a display to show it on. This takes about a minute.</p>'
      + '<button type="button" class="btn" onclick="wizardState.step = \'source\'; renderWizard();">Get started</button>';
  }
  el.innerHTML = html;
}

// Delegated (matches #nav's/#main's own click handling elsewhere in this
// shell): a click on one of the picker grid's cards - built by the shared
// componentCard(), an <a href="#component/...">- marks the wizard active
// and records where "Continue" should return to, then lets the anchor's
// own href navigate normally.
document.getElementById('section-wizard').addEventListener('click', function(e) {
  if (!e.target.closest('a.component-card')) return;
  if (wizardState.step === 'source') {
    wizardState = { active: true, step: 'source-detail', returnStep: 'output' };
  } else if (wizardState.step === 'output') {
    wizardState = { active: true, step: 'output-detail', returnStep: 'done' };
  }
});

// Called by components.js's renderComponentDetailBody() while a wizard step
// is in progress - a small banner above the normal detail page with a
// Continue action, enabled once the component has actually been saved as
// enabled (not just edited locally).
function wizardBannerHtml() {
  if (!wizardState.active) return '';
  var ready = !!(detailComponent && detailComponent.enabled) && !hasUnsavedComponentEdits;
  var what = wizardState.returnStep === 'output' ? 'source' : 'display';
  return '<div class="wizard-banner">'
    + '<span>Setting up a ' + what + ' &middot; save it below to continue.</span>'
    + '<button type="button" class="btn"' + (ready ? '' : ' disabled') + ' onclick="wizardContinue();">Continue</button>'
    + '</div>';
}

function wizardContinue() {
  var next = wizardState.returnStep;
  wizardState = { active: next !== 'done', step: next, returnStep: null };
  location.hash = 'wizard';
}
