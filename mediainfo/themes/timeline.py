"""Timeline theme: a list of the artist's other albums alongside the
current one - see mediainfo/config/themes.py's TimelineConfig.

Music-only by design (built from NowPlaying.discography, which is only
ever populated by the Lidarr enricher for music - see the roadmap plan).
Server-side/one-shot: prepare() extracts a deduplicated, ordered album
list from discography's "<album> - <track>" entries and pushes it as
plain data (extra_payload), like Color Palette - cheap enough that no
baking/caching is needed.

Degrades to showing just the current album when discography is empty
(the common case - it needs the optional, off-by-default Lidarr enricher
configured and the artist actually found in it), rather than hiding, per
the roadmap plan's explicit spec. Tracks that degraded state on the
instance (constructed once, reused across every prepare() call - see
mediainfo.outputs.themes.ThemesOutput._build_themes) so health_detail()
can report it, surfaced on /health via ThemesOutput.health_check(). A
benign, low-stakes data race exists if two prepare() calls for this same
theme instance overlap across threads - not worth locking for a purely
informational health value.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from mediainfo.cache import ImageCache
from mediainfo.config.themes import TimelineConfig
from mediainfo.stores.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

_VALID_CORNERS = frozenset({"bottom-right", "bottom-left", "top-right", "top-left", "center"})

# Matches mediainfo/enrichers/lidarr.py's _build_discography, which joins
# "{album_title} – {track_title}" with an en dash - not a hyphen.
_ALBUM_TRACK_SEP = " – "


def _extract_albums(discography: List[str], max_albums: int) -> List[str]:
    """Deduplicated album titles from discography's "<album> - <track>"
    entries, in first-seen order (discography itself has no guaranteed
    order - see NowPlaying's own docstring). Entries with no attributable
    album (lidarr.py falls back to a bare track title when it couldn't
    resolve one) are skipped, not attributed to a title-less "" album."""
    albums: List[str] = []
    for entry in discography:
        if _ALBUM_TRACK_SEP not in entry:
            continue
        album = entry.split(_ALBUM_TRACK_SEP, 1)[0].strip()
        if album and album not in albums:
            albums.append(album)
        if len(albums) >= max_albums:
            break
    return albums


class TimelineTheme(DisplayTheme):
    name = "timeline"

    def __init__(self) -> None:
        self._degraded_reason: Optional[str] = None

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: TimelineConfig,
    ) -> Optional[ThemeRenderResult]:
        if now_playing.media_type != "music":
            self._degraded_reason = None
            return None

        current = now_playing.album
        albums = _extract_albums(now_playing.discography, config.max_albums)

        if albums:
            self._degraded_reason = None
            if current and current not in albums:
                if len(albums) >= config.max_albums:
                    albums = albums[: max(0, config.max_albums - 1)]
                albums = [*albums, current]
        elif current:
            albums = [current]
            self._degraded_reason = (
                "No discography available (Lidarr not configured, or artist "
                "not found in it) - showing the current album only."
            )
        else:
            self._degraded_reason = "No album known for the current item."
            return None

        return ThemeRenderResult(extra_payload={"albums": albums, "current": current})

    def health_detail(self, config: TimelineConfig) -> Optional[dict]:
        if self._degraded_reason:
            return {"degraded": True, "reason": self._degraded_reason}
        return None

    def client_assets(self, config: TimelineConfig) -> ThemeClientAssets:
        corner = config.corner if config.corner in _VALID_CORNERS else "top-left"
        css = """
    #theme-timeline {
      position: absolute; z-index: 2; max-width: 20vw;
      opacity: 0; transition: opacity 0.8s ease-in-out;
      color: #fff; font-family: sans-serif; font-size: 1vw; line-height: 1.7;
      text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
    }
    #theme-timeline.visible { opacity: 1; }
    #theme-timeline.corner-bottom-right { bottom: 2vh; right: 2vw; text-align: right; }
    #theme-timeline.corner-bottom-left  { bottom: 2vh; left: 2vw; }
    #theme-timeline.corner-top-right    { top: 2vh; right: 2vw; text-align: right; }
    #theme-timeline.corner-top-left     { top: 2vh; left: 2vw; }
    #theme-timeline.corner-center       {
      top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center;
    }
    #theme-timeline .album {
      opacity: 0.6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    #theme-timeline .album.current { opacity: 1; font-weight: 700; }
"""
        js = f"""
    (function() {{
      var container = document.createElement('div');
      container.id = 'theme-timeline';
      container.className = 'theme-timeline corner-{corner}';
      document.getElementById('theme-layer').appendChild(container);

      window.themeHandlers.timeline = function(data) {{
        if (!data || !data.albums || !data.albums.length) {{
          container.classList.remove('visible');
          return;
        }}
        container.innerHTML = '';
        data.albums.forEach(function(name) {{
          var row = document.createElement('div');
          row.className = 'album' + (name === data.current ? ' current' : '');
          row.textContent = name;
          container.appendChild(row);
        }});
        container.classList.add('visible');
      }};
    }})();
"""
        return ThemeClientAssets(css=css, js=js)
