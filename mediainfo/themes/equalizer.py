"""Equalizer theme: a purely decorative "now playing audio" bar/wave
animation - see mediainfo/config/themes.py's EqualizerConfig.

This is **not** a real audio visualizer: no source in this codebase
exposes a PCM/FFT signal for it to react to (see the Display Themes
roadmap plan's Phase 10 note). It's a continuous, self-driven CSS
animation that just suggests audio activity while music is playing -
same spirit as Vinyl's decorative spin, which similarly can't detect
real play/pause state.

Purely client-side/continuous: prepare() only reports whether to show it
at all (music-only, gated on now_playing.media_type), never any per-item
data - the animation itself needs nothing from the current item.

All four screen corners are already claimed by other themes' defaults
(word_cloud=bottom-right, vinyl=bottom-left, media_mosaic=top-right,
timeline=top-left), so this renders as a full-width strip along the top
or bottom edge instead (config.position), like Color Palette's
swatch_position rather than the corner convention.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

from mediainfo.cache import ImageCache
from mediainfo.config.themes import EqualizerConfig
from mediainfo.stores.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

_VALID_POSITIONS = frozenset({"bottom", "top"})
_VALID_STYLES = frozenset({"bars", "wave"})

# A fixed (not per-config), gently rolling sine wave for style="wave" -
# two full cycles across a 0-200 viewBox, computed once at import time.
# Sampled at 48 points so it reads as smooth once stroked; start and end
# share the same phase/slope (sin(0) == sin(4*pi), same rising direction),
# so two copies placed side by side and scrolled tile seamlessly.
_WAVE_SAMPLE_COUNT = 48
_WAVE_PATH = " ".join(
    f"{'M' if i == 0 else 'L'}{(i / (_WAVE_SAMPLE_COUNT - 1)) * 200:.1f},"
    f"{50 - math.sin(i / (_WAVE_SAMPLE_COUNT - 1) * 4 * math.pi) * 28:.1f}"
    for i in range(_WAVE_SAMPLE_COUNT)
)


class EqualizerTheme(DisplayTheme):
    name = "equalizer"

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: EqualizerConfig,
    ) -> Optional[ThemeRenderResult]:
        if now_playing.media_type != "music":
            return None
        return ThemeRenderResult(extra_payload={"active": True})

    def client_assets(self, config: EqualizerConfig) -> ThemeClientAssets:
        position = config.position if config.position in _VALID_POSITIONS else "bottom"
        style = config.style if config.style in _VALID_STYLES else "bars"
        opacity = max(0.0, min(1.0, config.opacity))
        bar_count = max(1, min(64, config.bar_count))

        css = f"""
    #theme-equalizer {{
      position: absolute; left: 0; width: 100%; height: 14vh;
      opacity: 0; transition: opacity 1s ease-in-out;
      z-index: 2; pointer-events: none; box-sizing: border-box;
    }}
    #theme-equalizer.visible {{ opacity: {opacity}; }}
    #theme-equalizer.position-bottom {{ bottom: 0; }}
    #theme-equalizer.position-top {{ top: 0; }}

    #theme-equalizer.style-bars {{
      display: flex; align-items: flex-end; gap: 0.4vw; padding: 0 1vw;
    }}
    #theme-equalizer.style-bars.position-top {{ align-items: flex-start; }}
    #theme-equalizer .bar {{
      flex: 1 1 auto; min-width: 2px; border-radius: 2px 2px 0 0;
      background: linear-gradient(to top, rgba(255,255,255,0.5), rgba(255,255,255,0.95));
    }}
    #theme-equalizer.position-top .bar {{
      border-radius: 0 0 2px 2px;
      background: linear-gradient(to bottom, rgba(255,255,255,0.5), rgba(255,255,255,0.95));
    }}
    #theme-equalizer .bar.eq-1 {{ animation-name: theme-eq-bar-1; }}
    #theme-equalizer .bar.eq-2 {{ animation-name: theme-eq-bar-2; }}
    #theme-equalizer .bar.eq-3 {{ animation-name: theme-eq-bar-3; }}
    #theme-equalizer .bar.eq-4 {{ animation-name: theme-eq-bar-4; }}
    #theme-equalizer .bar {{ animation-timing-function: ease-in-out; animation-iteration-count: infinite; }}
    @keyframes theme-eq-bar-1 {{ 0%, 100% {{ height: 15%; }} 50% {{ height: 85%; }} }}
    @keyframes theme-eq-bar-2 {{ 0%, 100% {{ height: 45%; }} 50% {{ height: 20%; }} }}
    @keyframes theme-eq-bar-3 {{ 0%, 100% {{ height: 30%; }} 40% {{ height: 95%; }} 75% {{ height: 25%; }} }}
    @keyframes theme-eq-bar-4 {{ 0%, 100% {{ height: 55%; }} 30% {{ height: 10%; }} 65% {{ height: 78%; }} }}

    #theme-equalizer.style-wave {{ overflow: hidden; }}
    #theme-equalizer .wave-track {{
      display: flex; width: 200%; height: 100%;
      animation: theme-eq-wave-scroll 6s linear infinite;
    }}
    #theme-equalizer .wave-track svg {{ width: 50%; height: 100%; flex: 0 0 50%; display: block; }}
    @keyframes theme-eq-wave-scroll {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}
"""
        js = f"""
    (function() {{
      var STYLE = {json.dumps(style)};
      var BAR_COUNT = {bar_count};
      var WAVE_PATH = {json.dumps(_WAVE_PATH)};

      var wrap = document.createElement('div');
      wrap.id = 'theme-equalizer';
      wrap.className = 'theme-equalizer position-{position} style-{style}';
      document.getElementById('theme-layer').appendChild(wrap);

      if (STYLE === 'bars') {{
        for (var i = 0; i < BAR_COUNT; i++) {{
          var bar = document.createElement('div');
          bar.className = 'bar eq-' + ((i % 4) + 1);
          // Desync bars sharing a keyframe variant with a randomized
          // negative delay (so they don't all start their cycle in
          // lockstep) and a slightly randomized duration.
          bar.style.animationDuration = (0.7 + Math.random() * 0.9).toFixed(2) + 's';
          bar.style.animationDelay = (-Math.random() * 2).toFixed(2) + 's';
          wrap.appendChild(bar);
        }}
      }} else {{
        var track = document.createElement('div');
        track.className = 'wave-track';
        for (var t = 0; t < 2; t++) {{
          var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
          svg.setAttribute('viewBox', '0 0 200 100');
          svg.setAttribute('preserveAspectRatio', 'none');
          var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
          path.setAttribute('d', WAVE_PATH);
          path.setAttribute('stroke', 'rgba(255,255,255,0.85)');
          path.setAttribute('stroke-width', '3');
          path.setAttribute('fill', 'none');
          svg.appendChild(path);
          track.appendChild(svg);
        }}
        wrap.appendChild(track);
      }}

      window.themeHandlers.equalizer = function(data) {{
        if (!data || !data.active) {{
          wrap.classList.remove('visible');
          return;
        }}
        wrap.classList.add('visible');
      }};
    }})();
"""
        return ThemeClientAssets(css=css, js=js)
