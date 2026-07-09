"""Glow theme: a soft, slowly pulsing colored ambient glow behind the
artwork, colored from it by default - see mediainfo/config/themes.py's
GlowConfig.

The first theme that's genuinely both halves of the client-vs-server
split (see mediainfo/themes/base.py): prepare() computes the glow's color
once per resolved image (reusing mediainfo.colors.dominant_colors, the
same extraction Color Palette uses) and pushes it as plain data, cheap
enough to not need baking/caching - but the glow itself (fade-in, and the
slow pulse) is a pure CSS animation running entirely client-side, no
per-tick server work, unlike Color Palette (server data only, no
animation) or Blurred Background (a baked image, no animation).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PIL import Image

from mediainfo.cache import ImageCache
from mediainfo.colors import dominant_colors, to_hex
from mediainfo.config.themes import GlowConfig
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

logger = logging.getLogger(__name__)


class GlowTheme(DisplayTheme):
    name = "glow"

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: GlowConfig,
    ) -> Optional[ThemeRenderResult]:
        if config.color_source == "fixed":
            return ThemeRenderResult(extra_payload={"color": config.fixed_color})
        try:
            with Image.open(image_path) as image:
                colors = dominant_colors(image, count=1)
        except Exception:
            logger.exception("Glow: failed to read artwork %s", image_path)
            return None
        if not colors:
            return None
        return ThemeRenderResult(extra_payload={"color": to_hex(colors[0])})

    def client_assets(self, config: GlowConfig) -> ThemeClientAssets:
        intensity = max(0.0, min(1.0, config.intensity))
        pulse_class = " pulse" if config.pulse else ""
        css = f"""
    #theme-glow {{
      position: absolute; top: 50%; left: 50%; width: 60vmin; height: 60vmin;
      transform: translate(-50%, -50%);
      border-radius: 50%;
      filter: blur(80px);
      opacity: 0; transition: opacity 1.2s ease-in-out, background-color 1.2s ease-in-out;
      z-index: 0;
    }}
    #theme-glow.visible {{ opacity: {intensity}; }}
    #theme-glow.pulse {{ animation: theme-glow-pulse 5s ease-in-out infinite; }}
    @keyframes theme-glow-pulse {{
      0%, 100% {{ transform: translate(-50%, -50%) scale(1); }}
      50% {{ transform: translate(-50%, -50%) scale(1.15); }}
    }}
"""
        js = f"""
    (function() {{
      var glow = document.createElement('div');
      glow.id = 'theme-glow';
      glow.className = 'theme-glow{pulse_class}';
      document.getElementById('theme-layer').appendChild(glow);

      window.themeHandlers.glow = function(data) {{
        if (!data || !data.color) {{
          glow.classList.remove('visible');
          return;
        }}
        glow.style.backgroundColor = data.color;
        glow.classList.add('visible');
      }};
    }})();
"""
        return ThemeClientAssets(css=css, js=js)
