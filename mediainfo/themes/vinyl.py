"""Vinyl theme: shows the album art as a spinning vinyl record - see
mediainfo/config/themes.py's VinylThemeConfig.

Music-only by design (a record-player metaphor has no equivalent for
movies/TV, unlike every other theme so far - see the Display Themes
roadmap plan's media-type coverage table): prepare() produces nothing
outside now_playing.media_type == "music".

Purely client-side/continuous, like Ken Burns: prepare() only echoes back
the already-resolved image URL (no baking needed), and the spin itself is
a looping CSS `animation`. Deliberately decorative-only rotation - no
source reports real play/pause state today, so this can't stop spinning
on pause the way a real record player would; it spins whenever a music
item is showing and stops/hides otherwise (paused mid-song still shows it
spinning, a known simplification).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from mediainfo.cache import ImageCache
from mediainfo.config.themes import VinylThemeConfig
from mediainfo.stores.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

_VALID_CORNERS = frozenset({"bottom-right", "bottom-left", "top-right", "top-left", "center"})


class VinylTheme(DisplayTheme):
    name = "vinyl"

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: VinylThemeConfig,
    ) -> Optional[ThemeRenderResult]:
        if now_playing.media_type != "music":
            return None
        return ThemeRenderResult(extra_payload={"image": f"/image/current?v={image_path.stem}"})

    def client_assets(self, config: VinylThemeConfig) -> ThemeClientAssets:
        corner = config.corner if config.corner in _VALID_CORNERS else "bottom-left"
        rotation_seconds = max(1, config.rotation_seconds)
        # The outer wrapper only ever handles screen position + fade -
        # rotation lives entirely on the inner .disc, so a "center"
        # corner's own translate(-50%,-50%) positioning transform never
        # has to be combined with the spin transform on the same element.
        css = f"""
    #theme-vinyl {{
      position: absolute; width: {config.size_vmin}vmin; height: {config.size_vmin}vmin;
      opacity: 0; transition: opacity 1s ease-in-out;
      z-index: 2;
    }}
    #theme-vinyl.visible {{ opacity: 1; }}
    #theme-vinyl.corner-bottom-right {{ bottom: 2vh; right: 2vw; }}
    #theme-vinyl.corner-bottom-left  {{ bottom: 2vh; left: 2vw; }}
    #theme-vinyl.corner-top-right    {{ top: 2vh; right: 2vw; }}
    #theme-vinyl.corner-top-left     {{ top: 2vh; left: 2vw; }}
    #theme-vinyl.corner-center       {{ top: 50%; left: 50%; transform: translate(-50%, -50%); }}

    #theme-vinyl .disc {{
      position: relative; width: 100%; height: 100%; border-radius: 50%;
      background: repeating-radial-gradient(circle at center,
        #161616 0, #161616 3px, #0b0b0b 3px, #0b0b0b 6px);
      box-shadow: 0 8px 30px rgba(0, 0, 0, 0.5);
    }}
    #theme-vinyl .disc.spinning {{
      animation: theme-vinyl-spin {rotation_seconds}s linear infinite;
    }}
    @keyframes theme-vinyl-spin {{
      from {{ transform: rotate(0deg); }}
      to   {{ transform: rotate(360deg); }}
    }}
    #theme-vinyl .label {{
      position: absolute; top: 50%; left: 50%; width: 38%; height: 38%;
      transform: translate(-50%, -50%);
      border-radius: 50%; background-size: cover; background-position: center;
    }}
    #theme-vinyl .spindle {{
      position: absolute; top: 50%; left: 50%; width: 6%; height: 6%;
      transform: translate(-50%, -50%);
      border-radius: 50%; background: #000;
    }}
"""
        js = f"""
    (function() {{
      var wrap = document.createElement('div');
      wrap.id = 'theme-vinyl';
      wrap.className = 'theme-vinyl corner-{corner}';
      var disc = document.createElement('div');
      disc.className = 'disc';
      var label = document.createElement('div');
      label.className = 'label';
      var spindle = document.createElement('div');
      spindle.className = 'spindle';
      disc.appendChild(label);
      disc.appendChild(spindle);
      wrap.appendChild(disc);
      document.getElementById('theme-layer').appendChild(wrap);

      window.themeHandlers.vinyl = function(data) {{
        if (!data || !data.image) {{
          wrap.classList.remove('visible');
          disc.classList.remove('spinning');
          return;
        }}
        label.style.backgroundImage = 'url(' + data.image + ')';
        wrap.classList.add('visible');
        disc.classList.add('spinning');
      }};
    }})();
"""
        return ThemeClientAssets(css=css, js=js)
