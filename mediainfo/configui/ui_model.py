"""Data model for the redesigned config UI (Dashboard / Pipeline / component
detail views - see docs/gui-redesign-phase0-inventory.md for the overall
plan). These dataclasses describe the GUI declaratively; ui_builder.py
translates existing config/schema/health data into them. Nothing here reads
config.yaml or Flask request state directly - see ui_builder.py for that.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

# Top-level page a component belongs to.
UiCategory = str  # "media" | "metadata" | "appearance" | "display" | "library" | "health" | "system" | "advanced"

# UiComponent.status: "connected" | "enabled" | "disabled" |
# "needs_configuration" | "warning" | "error" | "restart_required" |
# "unknown". "warning" (Fas 10) is Health.WARNING translated via
# mediainfo.status.translate_availability - a real problem is not yet
# confirmed (e.g. a device that might just be briefly unreachable),
# distinct from "error"'s confirmed-broken meaning. "restart_required"
# (Foreman 001) is derived per output component from ConfigUiOutput.
# _restart_required_outputs (see ui_builder._output_components/
# _status_for) - only the specific output(s) whose outputs.* config
# changed since the last restart report it; UiDashboard.restart_required
# stays the separate, coarser global "does *something* need a restart"
# flag it always was. "missing_dependency" is still part of the
# vocabulary but not yet derivable from any existing signal (no
# structured "dependency missing" data) - reserved for a future phase
# rather than faked here.
UiStatus = str


@dataclasses.dataclass
class UiField:
    """One form field, already shaped for safe display: `value` is never a
    raw secret (mirrors ConfigStore's convention - secret fields carry ""
    here, with `secret_set` reporting whether one is actually configured).
    """

    name: str
    label: str
    help: str
    type: str
    required: bool
    secret: bool
    essential: bool
    value: Any
    secret_set: bool = False
    default: Any = None
    widget: Optional[str] = None
    choices: Optional[List[str]] = None


@dataclasses.dataclass
class UiAction:
    id: str
    label: str
    kind: str  # "link" | "test" | "restart" | ...
    href: Optional[str] = None


@dataclasses.dataclass
class UiComponent:
    id: str  # == config_path; already unique by construction
    name: str
    category: UiCategory
    component_type: str
    description: str
    enabled: bool
    configured: bool
    status: UiStatus
    health: str
    config_path: str
    supports_test: bool
    supports_multiple: bool
    requires_restart: bool
    essential_fields: List[UiField] = dataclasses.field(default_factory=list)
    advanced_fields: List[UiField] = dataclasses.field(default_factory=list)
    # _OutputFilterMixin fields (allow/deny media types & sources,
    # idle_when_filtered, active_hours, label) - only populated for output
    # components (see ui_builder._output_components()). Kept separate from
    # essential/advanced_fields so the detail page can render them as their
    # own "Content filters" block, matching the classic shell's app.html
    # (renderOutputFilters()) rather than mixing them in with the plugin's
    # own settings.
    filter_fields: List[UiField] = dataclasses.field(default_factory=list)
    warnings: List[str] = dataclasses.field(default_factory=list)
    actions: List[UiAction] = dataclasses.field(default_factory=list)
    # What the device is doing right now (Fas 10) - independent of
    # `status`/`health` above, which are about whether the integration is
    # actually broken. Only populated for component_type "source" (real
    # playback devices); everything else (outputs/enrichers/themes/flat
    # sections, and idle_source for now) leaves both None - see
    # mediainfo.status.Activity for the vocabulary and ui_builder.py's
    # build_components() for where this gets set.
    activity: Optional[str] = None
    activity_label: Optional[str] = None


@dataclasses.dataclass
class UiPipeline:
    id: str
    name: str
    media_component_ids: List[str] = dataclasses.field(default_factory=list)
    metadata_component_ids: List[str] = dataclasses.field(default_factory=list)
    appearance_component_ids: List[str] = dataclasses.field(default_factory=list)
    display_component_ids: List[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class UiHealthSummary:
    overall_status: str
    counts_by_status: Dict[str, int] = dataclasses.field(default_factory=dict)
    warnings: List[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class UiDashboard:
    status: str
    now_playing: Optional[dict]
    active_source: Optional[str]
    pipeline: UiPipeline
    health: UiHealthSummary
    restart_required: bool
    exposed_without_auth: bool
    quick_actions: List[UiAction] = dataclasses.field(default_factory=list)
    # Counts of source components by Activity value (playing/paused/idle/
    # sleeping/unknown - see mediainfo.status.Activity), Fas 10's device
    # summary ("Playing: 3, Idle: 5, Sleeping: 18, ..."). A different
    # dimension from counts_by_status above (every component, by
    # status) - this is sources only, by activity.
    activity_summary: Dict[str, int] = dataclasses.field(default_factory=dict)
    # True when no source and no output is enabled yet (Fas 11) - drives the
    # config UI's first-run setup wizard auto-redirect. Computed fresh from
    # the pipeline's enabled-component ids every request, never stored, so
    # it self-corrects the moment a source and an output are both enabled.
    needs_setup: bool = False
    # mediainfo.__version__ - shown on the Help page for bug reports; not
    # used for any compatibility check.
    app_version: str = ""
