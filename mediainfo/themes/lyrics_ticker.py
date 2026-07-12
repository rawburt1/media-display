"""Lyrics Ticker theme: a karaoke-style ticker highlighting the current
line of time-synced lyrics - see mediainfo/config/themes.py's
LyricsTickerConfig.

Music-only by design, built from NowPlaying.synced_lyrics (raw LRC text,
"[mm:ss.xx]line" per line - populated by text_enrichers.lrclib when the
current track has synced lyrics available; nothing new to fetch). No LRC
parser exists elsewhere in this codebase - mediainfo/lyrics_wordcloud.py's
_TIMESTAMP_RE only strips timestamps for the (unsynced) word cloud, it
doesn't capture them - so _parse_lrc() below is a small, self-contained
parser, not shared (this is its only consumer today).

Server-side/one-shot for the *parsing* (prepare() parses synced_lyrics
into a list of (seconds, text) cues once per item change, like Timeline
extracting an album list), but client-side/continuous for *advancing*
through those cues as playback continues - the same local, drift-
corrected clock trick the core themes page already uses for its own
small progress bar (see templates/themes/index.html's setProgress/
renderProgress), reimplemented self-contained here since no theme shares
state with another (see mediainfo/themes/base.py).

Degrades to nothing (not a hidden-but-still-"enabled" ticker) when synced
lyrics aren't available for the current track - the common case, since it
needs the optional text_enrichers.lrclib configured and the track actually
having synced lyrics on LRCLIB - and reports that via health_detail(),
same pattern as Timeline's own degraded-state reporting.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

from mediainfo.cache import ImageCache
from mediainfo.config.themes import LyricsTickerConfig
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

_VALID_POSITIONS = frozenset({"top", "bottom"})

_LRC_LINE_RE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\](.*)$")


def _parse_lrc(text: str) -> List[Tuple[float, str]]:
    """Parse LRC-formatted text into (seconds, line) cues, sorted by
    time. Lines without a leading "[mm:ss.xx]" tag (metadata tags like
    "[ar:Artist]", blank lines) are skipped, not treated as untimed
    lyrics - a ticker needs a time to anchor every line it shows."""
    cues: List[Tuple[float, str]] = []
    for line in text.splitlines():
        match = _LRC_LINE_RE.match(line)
        if not match:
            continue
        minutes, seconds, lyric = match.groups()
        lyric = lyric.strip()
        if lyric:
            cues.append((int(minutes) * 60 + float(seconds), lyric))
    return sorted(cues, key=lambda cue: cue[0])


class LyricsTickerTheme(DisplayTheme):
    name = "lyrics_ticker"

    def __init__(self) -> None:
        self._degraded_reason: Optional[str] = None

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: LyricsTickerConfig,
    ) -> Optional[ThemeRenderResult]:
        if now_playing.media_type != "music":
            self._degraded_reason = None
            return None

        cues = _parse_lrc(now_playing.synced_lyrics) if now_playing.synced_lyrics else []
        if not cues:
            self._degraded_reason = "No synced lyrics available for the current track."
            return None

        self._degraded_reason = None
        return ThemeRenderResult(
            extra_payload={
                "cues": [{"t": t, "text": text} for t, text in cues],
                "position_seconds": now_playing.position_seconds,
                "duration_seconds": now_playing.duration_seconds,
            }
        )

    def health_detail(self, config: LyricsTickerConfig) -> Optional[dict]:
        if self._degraded_reason:
            return {"degraded": True, "reason": self._degraded_reason}
        return None

    def client_assets(self, config: LyricsTickerConfig) -> ThemeClientAssets:
        position = config.position if config.position in _VALID_POSITIONS else "top"
        show_next_line = json.dumps(bool(config.show_next_line))
        css = """
    #theme-lyrics-ticker {
      position: absolute; left: 0; width: 100%;
      box-sizing: border-box; padding: 1.5vh 4vw; text-align: center;
      opacity: 0; transition: opacity 0.8s ease-in-out;
      z-index: 2; pointer-events: none;
      color: #fff; font-family: sans-serif;
      text-shadow: 0 1px 4px rgba(0, 0, 0, 0.85);
    }
    #theme-lyrics-ticker.visible { opacity: 1; }
    #theme-lyrics-ticker.position-top { top: 0; }
    #theme-lyrics-ticker.position-bottom { bottom: 0; }
    #theme-lyrics-ticker .current-line {
      font-size: 2vw; font-weight: 700; line-height: 1.3;
    }
    #theme-lyrics-ticker .next-line {
      font-size: 1.2vw; opacity: 0.55; margin-top: 0.4vh;
    }
"""
        js = f"""
    (function() {{
      var SHOW_NEXT_LINE = {show_next_line};
      var container = document.createElement('div');
      container.id = 'theme-lyrics-ticker';
      container.className = 'theme-lyrics-ticker position-{position}';
      var currentLine = document.createElement('div');
      currentLine.className = 'current-line';
      var nextLine = document.createElement('div');
      nextLine.className = 'next-line';
      container.appendChild(currentLine);
      container.appendChild(nextLine);
      document.getElementById('theme-layer').appendChild(container);

      // Payloads only arrive on item changes/rotation ticks, so the
      // active cue is advanced locally between them from the last
      // reported position (re-anchored on every new payload, correcting
      // for pauses/seeks) - same trick the core page's own small
      // progress bar uses (see templates/themes/index.html).
      var cues = [];
      var clock = null;

      function currentPosition() {{
        if (clock === null) return null;
        return clock.position + (Date.now() - clock.at) / 1000;
      }}

      function render() {{
        var pos = currentPosition();
        if (pos === null || !cues.length) {{
          container.classList.remove('visible');
          return;
        }}
        var activeIndex = -1;
        for (var i = 0; i < cues.length; i++) {{
          if (cues[i].t <= pos) activeIndex = i; else break;
        }}
        if (activeIndex === -1) {{
          container.classList.remove('visible');
          return;
        }}
        currentLine.textContent = cues[activeIndex].text;
        var next = cues[activeIndex + 1];
        nextLine.textContent = (SHOW_NEXT_LINE && next) ? next.text : '';
        container.classList.add('visible');
      }}

      window.themeHandlers.lyrics_ticker = function(data) {{
        if (!data || !data.cues || !data.cues.length) {{
          cues = [];
          clock = null;
          container.classList.remove('visible');
          return;
        }}
        cues = data.cues;
        clock = (typeof data.position_seconds === "number" && data.duration_seconds > 0)
          ? {{ position: data.position_seconds, at: Date.now() }}
          : null;
        render();
      }};

      setInterval(render, 500);
    }})();
"""
        return ThemeClientAssets(css=css, js=js)
