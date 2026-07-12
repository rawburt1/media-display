"""Word Cloud theme: shows a word cloud built from the current item's own
text, colored from its artwork - see mediainfo/config/themes.py's
WordCloudConfig.

Two branches, by media type:
  - music: reuses MediaDataStore.get_track_wordcloud() as-is - the same
    cached lyrics word cloud (see mediainfo/media_data_store.py and
    mediainfo/lyrics_wordcloud.py) the web output can already show via
    Artwork.is_wordcloud, just consumed here through the theme interface
    instead. Needs a MediaDataStore instance (wired in post-construction,
    see mediainfo.outputs.themes.ThemesOutput.set_media_data_store) and
    lyrics to actually be fetchable/cached for the playing track; produces
    nothing otherwise (no lyrics found, MediaDataStore not configured).
  - movie/episode: no per-item lyrics-shaped cache exists for a plot
    summary, so this calls mediainfo.lyrics_wordcloud.generate() directly
    against NowPlaying.summary (already populated by the Wikipedia
    enricher when configured), baking the result via
    ImageCache.get_derived_path the same way Blurred Background does -
    cached by (image, summary text) so replaying the same item is a cache
    hit, not a re-render.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image

from mediainfo.cache import ImageCache
from mediainfo.config.themes import WordCloudConfig
from mediainfo.lyrics_wordcloud import generate as generate_wordcloud
from mediainfo.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

logger = logging.getLogger(__name__)

_VALID_CORNERS = frozenset({"bottom-right", "bottom-left", "top-right", "top-left", "center"})


class WordCloudTheme(DisplayTheme):
    name = "word_cloud"

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: WordCloudConfig,
    ) -> Optional[ThemeRenderResult]:
        if now_playing.media_type == "music":
            return self._prepare_music(now_playing, media_data)
        if now_playing.media_type in ("movie", "episode"):
            return self._prepare_summary(now_playing, image_path, cache)
        return None

    def _prepare_music(
        self, now_playing: NowPlaying, media_data: Optional[MediaDataStore]
    ) -> Optional[ThemeRenderResult]:
        if media_data is None:
            return None
        # subtitle/album/title - same music-field convention every other
        # music enricher/theme already follows (see NowPlaying's docstring).
        artist, title, album = now_playing.subtitle, now_playing.title, now_playing.album
        if not artist or not title or not album:
            return None
        try:
            path = media_data.get_track_wordcloud(artist, album, title, now_playing.year)
        except Exception:
            logger.exception("Word Cloud: get_track_wordcloud failed for %r - %r", artist, title)
            return None
        if path is None:
            return None
        return ThemeRenderResult(derived_image_path=path)

    def _prepare_summary(
        self, now_playing: NowPlaying, image_path: Path, cache: ImageCache
    ) -> Optional[ThemeRenderResult]:
        text = now_playing.summary
        if not text:
            return None
        try:
            derived_path = cache.get_derived_path(
                image_path,
                self._cache_key(text),
                lambda _image: self._build_summary(image_path, text),
            )
        except Exception:
            logger.exception("Word Cloud: failed to build summary word cloud for %s", image_path)
            return None
        return ThemeRenderResult(derived_image_path=derived_path)

    @staticmethod
    def _cache_key(text: str) -> str:
        # "v1": bump if _build_summary's output ever changes shape for the
        # same text, so old cached derivatives don't linger stale.
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return f"summary_wordcloud_v1_{digest}"

    @staticmethod
    def _build_summary(image_path: Path, text: str) -> Image.Image:
        # generate() writes a PNG file (it drives the `wordcloud` package's
        # own layout, not something that hands back an in-memory Image
        # directly) and re-opens album_art_path by path itself rather than
        # taking an already-opened Image - so this renders to a temp file
        # and reads it back, the same trick MediaDataStore._render_wordcloud
        # uses to fit the FetchResult contract, here to fit
        # ImageCache.get_derived_path's Image-returning `build` contract.
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_out = Path(tmp_dir) / "wordcloud.png"
            generate_wordcloud(text, image_path, tmp_out, use_mask=False)
            with Image.open(tmp_out) as img:
                return img.copy()

    def client_assets(self, config: WordCloudConfig) -> ThemeClientAssets:
        corner = config.corner if config.corner in _VALID_CORNERS else "bottom-right"
        css = f"""
    #theme-word-cloud {{
      position: absolute; width: {config.size_vw}vw; max-width: {config.size_vw}vh;
      aspect-ratio: 1 / 1; z-index: 2;
      opacity: 0; transition: opacity 0.8s ease-in-out;
    }}
    #theme-word-cloud.visible {{ opacity: 1; }}
    #theme-word-cloud.corner-bottom-right {{ bottom: 2vh; right: 2vw; }}
    #theme-word-cloud.corner-bottom-left {{ bottom: 2vh; left: 2vw; }}
    #theme-word-cloud.corner-top-right {{ top: 2vh; right: 2vw; }}
    #theme-word-cloud.corner-top-left {{ top: 2vh; left: 2vw; }}
    #theme-word-cloud.corner-center {{
      top: 50%; left: 50%; transform: translate(-50%, -50%);
    }}
"""
        js = f"""
    (function() {{
      var img = document.createElement('img');
      img.id = 'theme-word-cloud';
      img.className = 'theme-word-cloud corner-{corner}';
      img.alt = '';
      document.getElementById('theme-layer').appendChild(img);

      window.themeHandlers.word_cloud = function(data) {{
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
