"""Now Playing Progress theme: a real-data (not decorative, unlike
Equalizer) full-width playback progress border along one screen edge -
see mediainfo/config/themes.py's ProgressBarConfig.

Media-type-agnostic: shows whenever a source reports both position and
duration (same condition mediainfo.outputs.websocket_push.
add_playback_position already uses for the top-level payload), regardless
of music/movie/episode. A brand new, separate DOM element
(#theme-progress-bar) - deliberately does not touch the themes page's own
pre-existing small centered #progress/#progress-fill bar
(templates/themes/index.html), which is unrelated core UI, not part of
the theme system.

`config.color` is threaded through the JSON payload (extra_payload),
never spliced into the server-rendered CSS text block at client_assets()
construction time - the same precedent mediainfo/themes/glow.py already
established for its own free-form fixed_color string, applied client-side
via `element.style.background = data.color`. This sidesteps any need to
validate/sanitize the string: an invalid CSS color value is simply
ignored by the browser, never executed as code, unlike a value spliced
directly into generated HTML/CSS/JS text.

Purely client-side/continuous once it has position/duration: prepare()
only reports the current numbers once per item/tick, and the fill
advances between payloads via the same local, drift-corrected clock
trick every other real-time theme in this codebase uses (Lyrics Ticker,
and the core page's own small progress bar).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from mediainfo.cache import ImageCache
from mediainfo.config.themes import ProgressBarConfig
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

_VALID_POSITIONS = frozenset({"top", "bottom"})


class ProgressBarTheme(DisplayTheme):
    name = "progress_bar"

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: ProgressBarConfig,
    ) -> Optional[ThemeRenderResult]:
        if not now_playing.duration_seconds or now_playing.position_seconds is None:
            return None
        return ThemeRenderResult(extra_payload={
            "position_seconds": now_playing.position_seconds,
            "duration_seconds": now_playing.duration_seconds,
            "color": config.color,
        })

    def client_assets(self, config: ProgressBarConfig) -> ThemeClientAssets:
        position = config.position if config.position in _VALID_POSITIONS else "bottom"
        thickness = max(1, config.thickness_px)
        css = f"""
    #theme-progress-bar {{
      position: absolute; left: 0; width: 100%; height: {thickness}px;
      background: rgba(255, 255, 255, 0.15);
      opacity: 0; transition: opacity 0.8s ease-in-out;
      z-index: 3; pointer-events: none;
    }}
    #theme-progress-bar.visible {{ opacity: 1; }}
    #theme-progress-bar.position-top {{ top: 0; }}
    #theme-progress-bar.position-bottom {{ bottom: 0; }}
    #theme-progress-bar .fill {{
      height: 100%; width: 0%; background: #fff;
    }}
"""
        js = f"""
    (function() {{
      var bar = document.createElement('div');
      bar.id = 'theme-progress-bar';
      bar.className = 'theme-progress-bar position-{position}';
      var fill = document.createElement('div');
      fill.className = 'fill';
      bar.appendChild(fill);
      document.getElementById('theme-layer').appendChild(bar);

      // Payloads only arrive on item changes/rotation ticks, so the fill
      // advances locally at 1s/s from the last reported position between
      // them (re-anchored on every new payload, correcting for pauses/
      // seeks) - same trick the core page's own small progress bar uses.
      var clock = null;

      function render() {{
        if (clock === null) {{
          bar.classList.remove('visible');
          return;
        }}
        var pos = Math.min(clock.position + (Date.now() - clock.at) / 1000, clock.duration);
        fill.style.width = (100 * pos / clock.duration) + '%';
        bar.classList.add('visible');
      }}

      window.themeHandlers.progress_bar = function(data) {{
        var valid = data && typeof data.position_seconds === "number" && data.duration_seconds > 0;
        clock = valid ? {{ position: data.position_seconds, duration: data.duration_seconds, at: Date.now() }} : null;
        if (valid && data.color) fill.style.background = data.color;
        render();
      }};

      setInterval(render, 1000);
    }})();
"""
        return ThemeClientAssets(css=css, js=js)
