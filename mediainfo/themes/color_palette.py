"""Color Palette theme: shows the current artwork's dominant colors as a
strip of swatches - see mediainfo/config/themes.py's ColorPaletteConfig.

Purely server-side/one-shot (see mediainfo/themes/base.py's client-vs-
server split): prepare() computes a small list of colors once per resolved
image and pushes them as plain data (extra_payload), not a baked image -
cheap enough (PIL quantize+getcolors on an already-downloaded image) that
there's no need for ImageCache.get_derived_path baking/caching here, unlike
themes that composite a new image (e.g. a future Blurred Background theme).
The swatch strip itself is laid out client-side via CSS/JS (client_assets),
following the same "server computes data once, browser lays it out with
CSS" split the Display Themes roadmap plan recommends for this kind of
theme.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PIL import Image

from mediainfo.cache import ImageCache
from mediainfo.imaging.colors import dominant_colors, to_hex
from mediainfo.config.themes import ColorPaletteConfig
from mediainfo.stores.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

logger = logging.getLogger(__name__)

_VALID_POSITIONS = frozenset({"bottom", "top", "side"})


class ColorPaletteTheme(DisplayTheme):
    name = "color_palette"

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: ColorPaletteConfig,
    ) -> Optional[ThemeRenderResult]:
        try:
            with Image.open(image_path) as image:
                colors = dominant_colors(image, count=config.swatch_count)
        except Exception:
            logger.exception("Color Palette: failed to read artwork %s", image_path)
            return None
        if not colors:
            return None
        return ThemeRenderResult(extra_payload={"colors": [to_hex(c) for c in colors]})

    def client_assets(self, config: ColorPaletteConfig) -> ThemeClientAssets:
        # Falls back to "bottom" for an unrecognised value (e.g. a config
        # typo) rather than injecting an arbitrary string straight into
        # the generated CSS/JS.
        position = (
            config.swatch_position if config.swatch_position in _VALID_POSITIONS else "bottom"
        )
        position_class = f"position-{position}"
        css = """
    #theme-color-palette {
      position: absolute; z-index: 2; display: flex;
      opacity: 0; transition: opacity 0.6s ease-in-out;
      pointer-events: none;
    }
    #theme-color-palette.visible { opacity: 1; }
    #theme-color-palette.position-bottom, #theme-color-palette.position-top {
      left: 0; width: 100%; height: 6vh; flex-direction: row;
    }
    #theme-color-palette.position-bottom { bottom: 0; }
    #theme-color-palette.position-top { top: 0; }
    #theme-color-palette.position-side {
      top: 0; left: 0; width: 4vw; height: 100%; flex-direction: column;
    }
    #theme-color-palette .swatch { flex: 1; }
"""
        js = f"""
    (function() {{
      var container = document.createElement('div');
      container.id = 'theme-color-palette';
      container.className = 'theme-color-palette {position_class}';
      document.getElementById('theme-layer').appendChild(container);

      window.themeHandlers.color_palette = function(data) {{
        if (!data || !data.colors || !data.colors.length) {{
          container.classList.remove('visible');
          return;
        }}
        container.innerHTML = '';
        data.colors.forEach(function(hex) {{
          var swatch = document.createElement('div');
          swatch.className = 'swatch';
          swatch.style.backgroundColor = hex;
          container.appendChild(swatch);
        }});
        container.classList.add('visible');
      }};
    }})();
"""
        return ThemeClientAssets(css=css, js=js)
