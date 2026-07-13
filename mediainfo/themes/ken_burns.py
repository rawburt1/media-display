"""Ken Burns theme: a slow, continuous pan/zoom on the artwork - the
classic documentary-style effect - see mediainfo/config/themes.py's
KenBurnsConfig.

Purely client-side/continuous (see mediainfo/themes/base.py's client-vs-
server split): prepare() only echoes back the already-resolved image URL
(no new file, no baking - the same image ThemesOutput already registered
in _known_images when it resolved the current artwork), and the pan/zoom
itself is a CSS `animation` (not `transition`, so it loops continuously
rather than settling after one run) on a dedicated layer.

Deliberately never touches the foreground #art-a/#art-b elements or their
existing crossfade transitions (transitions.py) - those use `transition:
transform` for a one-shot settle-in effect per image change, which a
continuously-looping `animation` on the same property would fight. Instead
this renders its own animated copy of the artwork into #theme-layer,
behind the static foreground art, in the same letterbox space Blurred
Background occupies - visible around/behind the sharp foreground image,
never replacing it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from mediainfo.cache import ImageCache
from mediainfo.config.themes import KenBurnsConfig
from mediainfo.stores.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

# CSS animation-name/class for each pan/zoom variant, one picked at random
# per image change (mirrors mediainfo/outputs/transitions.py's own
# variant-picking pattern for the foreground crossfade).
_VARIANTS = ["kb-zoom-in", "kb-zoom-out", "kb-pan"]


class KenBurnsTheme(DisplayTheme):
    name = "ken_burns"

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: KenBurnsConfig,
    ) -> Optional[ThemeRenderResult]:
        return ThemeRenderResult(extra_payload={"image": f"/image/current?v={image_path.stem}"})

    def client_assets(self, config: KenBurnsConfig) -> ThemeClientAssets:
        duration = max(1, config.duration_seconds)
        opacity = max(0.0, min(1.0, config.opacity))
        css = f"""
    #theme-ken-burns {{
      position: absolute; top: 0; left: 0; width: 100%; height: 100%;
      object-fit: cover; transform-origin: center center;
      opacity: 0; transition: opacity 1.2s ease-in-out;
      z-index: 0;
    }}
    #theme-ken-burns.visible {{ opacity: {opacity}; }}
    #theme-ken-burns.kb-zoom-in  {{ animation: theme-kb-zoom-in {duration}s ease-in-out infinite alternate; }}
    #theme-ken-burns.kb-zoom-out {{ animation: theme-kb-zoom-out {duration}s ease-in-out infinite alternate; }}
    #theme-ken-burns.kb-pan      {{ animation: theme-kb-pan {duration}s ease-in-out infinite alternate; }}
    @keyframes theme-kb-zoom-in  {{ from {{ transform: scale(1); }} to {{ transform: scale(1.15); }} }}
    @keyframes theme-kb-zoom-out {{ from {{ transform: scale(1.15); }} to {{ transform: scale(1); }} }}
    @keyframes theme-kb-pan {{
      from {{ transform: scale(1.1) translate(-2%, -2%); }}
      to   {{ transform: scale(1.1) translate(2%, 2%); }}
    }}
"""
        js = f"""
    (function() {{
      var VARIANTS = {json.dumps(_VARIANTS)};
      var img = document.createElement('img');
      img.id = 'theme-ken-burns';
      img.alt = '';
      document.getElementById('theme-layer').appendChild(img);

      var lastImage = null;
      window.themeHandlers.ken_burns = function(data) {{
        if (!data || !data.image) {{
          img.classList.remove('visible');
          return;
        }}
        if (data.image !== lastImage) {{
          img.classList.remove(...VARIANTS);
          img.classList.add(VARIANTS[Math.floor(Math.random() * VARIANTS.length)]);
          img.src = data.image;
          lastImage = data.image;
        }}
        img.classList.add('visible');
      }};
    }})();
"""
        return ThemeClientAssets(css=css, js=js)
