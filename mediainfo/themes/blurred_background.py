"""Blurred Background theme: fills the screen behind the sharp foreground
artwork with a heavily blurred, darkened copy of it - see
mediainfo/config/themes.py's BlurredBackgroundConfig.

Server-side/one-shot (see mediainfo/themes/base.py's client-vs-server
split), but unlike Color Palette this bakes a real composite image rather
than pushing plain data, so it reuses ImageCache.get_derived_path exactly
the way Pixoo's LED-preparation pipeline already does: cached on disk
keyed by (original image stem, settings), so repeat calls for the same
image+settings are a cache hit, not a re-blur.

The source image is downscaled *before* blurring, not after: blurring at
full resolution is both slower (GaussianBlur cost scales with pixel count)
and, counter-intuitively, doesn't look as soft once the browser scales the
result back up to fill the screen via CSS `background-size: cover` - a
small blurred image stretched large reads as a smooth, soft gradient (the
same trick behind Spotify/Apple Music-style "ambient" backgrounds),
whereas blurring a huge image by the same pixel radius barely softens it
at that scale.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageEnhance, ImageFilter

from mediainfo.cache import ImageCache
from mediainfo.config.themes import BlurredBackgroundConfig
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

logger = logging.getLogger(__name__)

# Longest edge, in pixels, to downscale to before blurring - see the
# module docstring for why smaller-then-blurred beats full-res-then-blurred.
_DOWNSCALE_SIZE = 400


class BlurredBackgroundTheme(DisplayTheme):
    name = "blurred_background"

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: BlurredBackgroundConfig,
    ) -> Optional[ThemeRenderResult]:
        try:
            derived_path = cache.get_derived_path(
                image_path, self._cache_key(config), lambda image: self._build(image, config),
            )
        except Exception:
            logger.exception("Blurred Background: failed to build background for %s", image_path)
            return None
        return ThemeRenderResult(derived_image_path=derived_path)

    @staticmethod
    def _cache_key(config: BlurredBackgroundConfig) -> str:
        # "v1": bump if _build's output ever changes shape for the same
        # settings, so old cached derivatives don't linger stale.
        return f"blurbg_v1_{config.blur_radius}_{config.brightness}"

    @staticmethod
    def _build(image: Image.Image, config: BlurredBackgroundConfig) -> Image.Image:
        img = image.convert("RGB")
        img.thumbnail((_DOWNSCALE_SIZE, _DOWNSCALE_SIZE))
        img = img.filter(ImageFilter.GaussianBlur(config.blur_radius))
        if config.brightness != 1.0:
            img = ImageEnhance.Brightness(img).enhance(config.brightness)
        return img

    def client_assets(self, config: BlurredBackgroundConfig) -> ThemeClientAssets:
        css = """
    #theme-blurred-background {
      position: absolute; top: 0; left: 0; width: 100%; height: 100%;
      background-size: cover; background-position: center;
      opacity: 0; transition: opacity 0.8s ease-in-out;
    }
    #theme-blurred-background.visible { opacity: 1; }
"""
        js = """
    (function() {
      var bg = document.createElement('div');
      bg.id = 'theme-blurred-background';
      document.getElementById('theme-layer').appendChild(bg);

      window.themeHandlers.blurred_background = function(data) {
        if (!data || !data.image) {
          bg.classList.remove('visible');
          return;
        }
        bg.style.backgroundImage = 'url(' + data.image + ')';
        bg.classList.add('visible');
      };
    })();
"""
        return ThemeClientAssets(css=css, js=js)
