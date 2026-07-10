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

# UiComponent.status. "missing_dependency" and "restart_required" are part
# of the vocabulary but not yet derivable from any existing signal (no
# structured "dependency missing" data, and restart-required is only
# tracked globally, not per component - see UiDashboard.restart_required)
# - reserved for a future phase rather than faked here.
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
    warnings: List[str] = dataclasses.field(default_factory=list)
    actions: List[UiAction] = dataclasses.field(default_factory=list)


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
