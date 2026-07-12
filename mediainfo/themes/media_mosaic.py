"""Media Mosaic theme: a grid of related artwork alongside the current
pick - other albums by the artist, other posters/fanart for the item -
see mediainfo/config/themes.py's MediaMosaicConfig.

Server-side/one-shot, but unlike every other one-shot theme so far, this
is the first that needs the *entire* image pool (now_playing.images), not
just the single artwork/image_path the orchestrator already resolved for
this tick - both are already DisplayTheme.prepare() parameters, so no new
hook was needed (see the Display Themes roadmap plan). Degrades to a
single tile when only one candidate image is available (still shown, not
hidden). Excludes artist-photo and word-cloud images from the tile pool -
those aren't "other artwork for this item," they'd look out of place in
a grid meant for covers/posters/fanart.
"""

from __future__ import annotations

import hashlib
import logging
import math
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageOps

from mediainfo.cache import CacheTier, ImageCache
from mediainfo.config.themes import MediaMosaicConfig
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

logger = logging.getLogger(__name__)

_VALID_CORNERS = frozenset({"bottom-right", "bottom-left", "top-right", "top-left", "center"})
_TILE_SIZE = 300
_HIGHLIGHT_BORDER = 8

# Grid dimensions (cols, rows) that pack common tile counts without an
# empty cell - falls back to ceil(sqrt(n)) beyond this for any higher
# max_tiles a user configures.
_GRID_LAYOUTS = {1: (1, 1), 2: (2, 1), 3: (3, 1), 4: (2, 2), 5: (3, 2), 6: (3, 2)}


def _grid_dims(count: int) -> Tuple[int, int]:
    if count in _GRID_LAYOUTS:
        return _GRID_LAYOUTS[count]
    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)
    return cols, rows


class MediaMosaicTheme(DisplayTheme):
    name = "media_mosaic"

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: MediaMosaicConfig,
    ) -> Optional[ThemeRenderResult]:
        tier: CacheTier = "music" if now_playing.media_type == "music" else "default"
        candidates = self._candidate_tiles(now_playing)[: max(1, config.max_tiles)]

        resolved: List[Path] = []
        for item in candidates:
            try:
                path = cache.get_path(item, tier=tier)
            except Exception:
                logger.exception("Media Mosaic: failed to resolve %s", item.url)
                continue
            if path is not None:
                resolved.append(path)

        if not resolved:
            return None

        try:
            derived_path = cache.get_derived_path(
                image_path,
                self._cache_key(resolved, config),
                lambda _image: self._build_mosaic(resolved, image_path),
            )
        except Exception:
            logger.exception("Media Mosaic: failed to build mosaic")
            return None
        return ThemeRenderResult(derived_image_path=derived_path)

    @staticmethod
    def _candidate_tiles(now_playing: NowPlaying) -> List[Artwork]:
        return [
            img for img in now_playing.images if not img.is_artist_photo and not img.is_wordcloud
        ]

    @staticmethod
    def _cache_key(paths: List[Path], config: MediaMosaicConfig) -> str:
        # "v1": bump if _build_mosaic's output ever changes shape for the
        # same inputs, so old cached mosaics don't linger stale. Sorted so
        # the same pool in a different order still hits the cache.
        digest = hashlib.sha256(
            "|".join(sorted(p.stem for p in paths)).encode("utf-8")
        ).hexdigest()[:16]
        return f"mosaic_v1_{config.max_tiles}_{digest}"

    @staticmethod
    def _build_mosaic(paths: List[Path], current_path: Path) -> Image.Image:
        cols, rows = _grid_dims(len(paths))
        canvas = Image.new("RGB", (_TILE_SIZE * cols, _TILE_SIZE * rows), (0, 0, 0))
        for i, path in enumerate(paths):
            with Image.open(path) as image:
                tile = ImageOps.fit(image.convert("RGB"), (_TILE_SIZE, _TILE_SIZE))
            if path == current_path:
                # Highlight the tile matching what's already shown as the
                # main artwork, so it reads as "you are here" among the
                # rest of the grid.
                tile = ImageOps.expand(tile, border=_HIGHLIGHT_BORDER, fill=(255, 255, 255))
                tile = tile.resize((_TILE_SIZE, _TILE_SIZE))
            x = (i % cols) * _TILE_SIZE
            y = (i // cols) * _TILE_SIZE
            canvas.paste(tile, (x, y))
        return canvas

    def client_assets(self, config: MediaMosaicConfig) -> ThemeClientAssets:
        corner = config.corner if config.corner in _VALID_CORNERS else "top-right"
        css = f"""
    #theme-media-mosaic {{
      position: absolute; max-width: {config.size_vw}vw; max-height: {config.size_vw}vh;
      z-index: 2; border-radius: 4px;
      opacity: 0; transition: opacity 0.8s ease-in-out;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
    }}
    #theme-media-mosaic.visible {{ opacity: 1; }}
    #theme-media-mosaic.corner-bottom-right {{ bottom: 2vh; right: 2vw; }}
    #theme-media-mosaic.corner-bottom-left  {{ bottom: 2vh; left: 2vw; }}
    #theme-media-mosaic.corner-top-right    {{ top: 2vh; right: 2vw; }}
    #theme-media-mosaic.corner-top-left     {{ top: 2vh; left: 2vw; }}
    #theme-media-mosaic.corner-center       {{ top: 50%; left: 50%; transform: translate(-50%, -50%); }}
"""
        js = f"""
    (function() {{
      var img = document.createElement('img');
      img.id = 'theme-media-mosaic';
      img.className = 'theme-media-mosaic corner-{corner}';
      img.alt = '';
      document.getElementById('theme-layer').appendChild(img);

      window.themeHandlers.media_mosaic = function(data) {{
        if (!data || !data.image) {{
          img.classList.remove('visible');
          return;
        }}
        img.onload = function() {{ img.classList.add('visible'); }};
        img.src = data.image;
      }};
    }})();
"""
        return ThemeClientAssets(css=css, js=js)
