"""Base class for Display Theme plugins - see mediainfo/outputs/themes.py.

A theme is either (or both):
  - client-side/continuous: contributes CSS/JS injected into the themes
    page once, then animates itself in the browser between server pushes
    (like mediainfo/outputs/transitions.py's fade/slide/zoom, or the web
    output's own client-side progress-bar interpolation) - cheap, no
    per-tick server work.
  - server-side/one-shot: computes/bakes something once per item change
    (a derived image via ImageCache.get_derived_path, or precomputed
    values like a color palette) and contributes it as extra data the
    client lays out via CSS - avoids re-baking large images every
    rotation tick.

Several themes enabled at once all contribute independently into the same
page render - a theme never knows or cares what other themes are also
enabled (see ThemesOutput).
"""

from __future__ import annotations

import dataclasses
from abc import ABC
from pathlib import Path
from typing import Any, Dict, Optional

from mediainfo.cache import ImageCache
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying


@dataclasses.dataclass
class ThemeClientAssets:
    """CSS/JS one theme contributes to the themes page, injected once at
    page-render time (mirrors WebOutput's own self._transitions_css/
    self._transitions_js, built once per output rather than per request)."""

    css: str = ""
    js: str = ""
    # Small values the client-side JS needs beyond title/subtitle/image
    # (e.g. rotation speed, glow color) - merged into the WebSocket
    # payload under payload["themes"][theme_name].
    client_config: Dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ThemeRenderResult:
    """What one theme's prepare() computed for the current item."""

    # Extra JSON fields merged into the WebSocket payload under
    # payload["themes"][theme_name], for the client to lay out via CSS.
    extra_payload: Dict[str, Any] = dataclasses.field(default_factory=dict)
    # A baked derivative image path (via ImageCache.get_derived_path),
    # exposed as an extra image URL if the theme needs a full composite -
    # None if extra_payload alone is enough.
    derived_image_path: Optional[Path] = None


class DisplayTheme(ABC):
    """One visual effect layered on top of the current artwork/metadata in
    the `themes` output. Subclasses implement whichever of client_assets()/
    prepare() applies - neither is required, though a theme implementing
    neither would have no visible effect."""

    # Registry key, e.g. "glow" - set by subclasses, matching their entry
    # in mediainfo.themes.THEME_CLASSES and mediainfo.config.themes.
    # THEMES_CONFIG_TYPES.
    name: str

    def client_assets(self, config: Any) -> Optional[ThemeClientAssets]:
        """CSS/JS injected once into the themes page. None (the default)
        if this theme has no client-side component."""
        return None

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: Any,
    ) -> Optional[ThemeRenderResult]:
        """Compute/bake this theme's contribution for the artwork/image
        currently being shown (called from ThemesOutput.update(), whenever
        the orchestrator resolves a new image - once per item for a
        single-image pool, or once per rotation tick through a multi-image
        pool). None (the default) if this theme has no per-item server-side
        work, or couldn't produce anything for the current item (e.g. a
        Timeline theme with no discography). Implementations that bake an
        expensive derivative should key their cache off `image_path` (e.g.
        via ImageCache.get_derived_path) so repeat calls for the same image
        are cheap."""
        return None

    def health_detail(self, config: Any) -> Optional[dict]:
        """Optional degraded-state detail (e.g. "no discography -
        showing single item"), aggregated by ThemesOutput.health_check()
        into /health. None (the default) means nothing to report."""
        return None
