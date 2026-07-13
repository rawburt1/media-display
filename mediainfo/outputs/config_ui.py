"""Thin adapter: ConfigUiOutput's real implementation lives in
mediainfo/configui/output.py (M6 in
docs/architecture-usability-review-2026-07.md - "the config UI backend
lives inside outputs/ because it happens to be delivered as an Output
plugin", moved out since the backend itself has nothing to do with being
an Output).

This re-export exists so registries.py's dotted path
("mediainfo.outputs.config_ui.ConfigUiOutput") keeps resolving unchanged,
and so `outputs/` still shows every registered output plugin, including
this one, for anyone browsing that package. New code should import
ConfigUiOutput (or any of its internals) from mediainfo.configui.output
directly - see docs/adr/ for the rest of that module's own design
rationale.
"""

from __future__ import annotations

from mediainfo.configui.output import ConfigUiOutput

__all__ = ["ConfigUiOutput"]
