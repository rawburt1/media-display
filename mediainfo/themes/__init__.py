"""Display Theme plugins - see mediainfo/themes/base.py for the DisplayTheme
interface and mediainfo/outputs/themes.py for the output that hosts them.

Registered in mediainfo.registries.THEME_CLASSES, the same lazy-resolved
dotted-path pattern used for sources/outputs/enrichers, and configured via
mediainfo.config.themes.THEMES_CONFIG_TYPES.
"""

from __future__ import annotations

from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

__all__ = ["DisplayTheme", "ThemeClientAssets", "ThemeRenderResult"]
