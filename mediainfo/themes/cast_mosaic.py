"""Cast/Crew Mosaic theme: a grid of top-billed cast headshots for the
current movie/TV item - see mediainfo/config/themes.py's
CastMosaicConfig.

Movie/TV only (there's no cast concept for music). Needs
NowPlaying.cast populated - the optional, off-by-default
enrichers.tmdb.fetch_cast credits fetch (see mediainfo/enrichers/
tmdb.py) - and degrades to nothing when unavailable, reported via
health_detail() same as Timeline.

Server-side/one-shot, but unlike Media Mosaic (which bakes one composite
PNG via PIL, since it shows unlabeled tiles), this theme resolves each
cast member's headshot to a local file via ImageCache.get_path (the same
download-and-disk-cache primitive every other artwork source already
uses) but never composites them into pixels - each stays its own
individually-addressable image (ThemeRenderResult.derived_image_paths),
laid out as a CSS grid with real DOM <figcaption> name/character labels.
No PIL/ImageFont involved: this project has no bundled font, and DOM text
stays sharp/consistent with the rest of the page's typography rather than
being baked into a raster image.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from mediainfo.cache import ImageCache
from mediainfo.config.themes import CastMosaicConfig
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

logger = logging.getLogger(__name__)

_VALID_CORNERS = frozenset({"bottom-right", "bottom-left", "top-right", "top-left", "center"})


class CastMosaicTheme(DisplayTheme):
    name = "cast_mosaic"

    def __init__(self) -> None:
        self._degraded_reason: Optional[str] = None

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: CastMosaicConfig,
    ) -> Optional[ThemeRenderResult]:
        if now_playing.media_type not in ("movie", "episode"):
            self._degraded_reason = None
            return None

        if not now_playing.cast:
            self._degraded_reason = (
                "No cast data available - enable enrichers.tmdb.fetch_cast, "
                "or TMDb has no credits for this title."
            )
            return None

        cast: List[dict] = []
        paths: List[Path] = []
        for member in now_playing.cast[: max(1, config.max_cast)]:
            photo_url = member.get("photo_url")
            if not photo_url:
                continue
            try:
                path = cache.get_path(
                    Artwork(url=photo_url, label=member.get("name", "")), tier="default"
                )
            except Exception:
                logger.exception("Cast Mosaic: failed to resolve %s", photo_url)
                continue
            if path is None:
                continue
            paths.append(path)
            cast.append(
                {
                    "name": member.get("name", ""),
                    "character": member.get("character", ""),
                    "image": f"/image/current?v={path.stem}",
                }
            )

        if not cast:
            self._degraded_reason = "No cast headshots could be resolved for this title."
            return None

        self._degraded_reason = None
        return ThemeRenderResult(extra_payload={"cast": cast}, derived_image_paths=paths)

    def health_detail(self, config: CastMosaicConfig) -> Optional[dict]:
        if self._degraded_reason:
            return {"degraded": True, "reason": self._degraded_reason}
        return None

    def client_assets(self, config: CastMosaicConfig) -> ThemeClientAssets:
        corner = config.corner if config.corner in _VALID_CORNERS else "top-right"
        css = f"""
    #theme-cast-mosaic {{
      position: absolute; max-width: {config.size_vw}vw;
      opacity: 0; transition: opacity 0.8s ease-in-out;
      z-index: 2; display: grid; grid-template-columns: repeat(3, 1fr);
      gap: 0.6vw;
      font-family: sans-serif; color: #fff;
      text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
    }}
    #theme-cast-mosaic.visible {{ opacity: 1; }}
    #theme-cast-mosaic.corner-bottom-right {{ bottom: 2vh; right: 2vw; }}
    #theme-cast-mosaic.corner-bottom-left  {{ bottom: 2vh; left: 2vw; }}
    #theme-cast-mosaic.corner-top-right    {{ top: 2vh; right: 2vw; }}
    #theme-cast-mosaic.corner-top-left     {{ top: 2vh; left: 2vw; }}
    #theme-cast-mosaic.corner-center       {{
      top: 50%; left: 50%; transform: translate(-50%, -50%);
    }}
    #theme-cast-mosaic figure {{ margin: 0; text-align: center; }}
    #theme-cast-mosaic img {{
      width: 100%; aspect-ratio: 1 / 1; object-fit: cover;
      border-radius: 8px; display: block;
    }}
    #theme-cast-mosaic figcaption {{
      font-size: 0.7vw; line-height: 1.3; margin-top: 0.2vh;
    }}
    #theme-cast-mosaic figcaption .character {{ opacity: 0.65; }}
"""
        js = f"""
    (function() {{
      var container = document.createElement('div');
      container.id = 'theme-cast-mosaic';
      container.className = 'theme-cast-mosaic corner-{corner}';
      document.getElementById('theme-layer').appendChild(container);

      window.themeHandlers.cast_mosaic = function(data) {{
        if (!data || !data.cast || !data.cast.length) {{
          container.classList.remove('visible');
          return;
        }}
        container.innerHTML = '';
        data.cast.forEach(function(member) {{
          var figure = document.createElement('figure');
          var img = document.createElement('img');
          img.src = member.image;
          img.alt = member.name;
          var caption = document.createElement('figcaption');
          var name = document.createElement('div');
          name.textContent = member.name;
          caption.appendChild(name);
          if (member.character) {{
            var character = document.createElement('div');
            character.className = 'character';
            character.textContent = member.character;
            caption.appendChild(character);
          }}
          figure.appendChild(img);
          figure.appendChild(caption);
          container.appendChild(figure);
        }});
        container.classList.add('visible');
      }};
    }})();
"""
        return ThemeClientAssets(css=css, js=js)
