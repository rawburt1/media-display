"""Artist Spotlight theme: a portrait card with the current artist's
photo and a short bio blurb - see mediainfo/config/themes.py's
ArtistSpotlightConfig.

Fully "ready now" - no new data plumbing needed. Reuses two already-
existing, already-populated sources:
  - MediaDataStore.get_artist_photo(artist) (Wikipedia-first, Last.fm-
    fallback - mediainfo/media_data_store.py) for the photo. Needs a
    MediaDataStore instance (wired in post-construction, see
    mediainfo.outputs.themes.ThemesOutput.set_media_data_store) - the
    same requirement Word Cloud's music branch already has.
  - NowPlaying.summary for the bio - the Wikipedia enricher already
    populates it for media_type == "music" too (mediainfo/enrichers/
    wikipedia.py), not just movies/TV, treating a music item's artist
    the same way it treats the SVT-concert-broadcast `artist` field
    (both resolve an artist bio/photo rather than a movie/show one).

Server-side/one-shot: prepare() resolves the artist name once per item
(music: subtitle, per the codebase-wide title=song/subtitle=artist
convention; non-music: the dedicated `artist` field, e.g. an SVT concert
broadcast) and looks up its photo - cheap enough that MediaDataStore
already handles its own disk caching, no extra baking needed here.

Degrades to nothing when no artist name is resolvable (silently, the N/A
case - mirrors Vinyl/Lyrics Ticker/Cast Mosaic for media types the theme
doesn't apply to) versus when an artist *is* known but no photo could be
found (a real degraded case, reported via health_detail() like Timeline).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from mediainfo.cache import ImageCache
from mediainfo.config.themes import ArtistSpotlightConfig
from mediainfo.stores.media_data_store import MediaDataStore
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.base import DisplayTheme, ThemeClientAssets, ThemeRenderResult

_VALID_CORNERS = frozenset({"bottom-right", "bottom-left", "top-right", "top-left", "center"})


def _resolve_artist(now_playing: NowPlaying) -> str:
    if now_playing.media_type == "music":
        return now_playing.subtitle
    return now_playing.artist


class ArtistSpotlightTheme(DisplayTheme):
    name = "artist_spotlight"

    def __init__(self) -> None:
        self._degraded_reason: Optional[str] = None

    def prepare(
        self,
        now_playing: NowPlaying,
        artwork: Artwork,
        image_path: Path,
        cache: ImageCache,
        media_data: Optional[MediaDataStore],
        config: ArtistSpotlightConfig,
    ) -> Optional[ThemeRenderResult]:
        artist = _resolve_artist(now_playing)
        if not artist:
            self._degraded_reason = None
            return None

        if media_data is None:
            self._degraded_reason = (
                "MediaDataStore is not configured - enable enrichers.mediadata "
                "to show artist photos."
            )
            return None

        photo_path = media_data.get_artist_photo(artist)
        if photo_path is None:
            self._degraded_reason = f"No photo found for {artist!r}."
            return None

        self._degraded_reason = None
        bio = now_playing.summary if config.show_bio else ""
        return ThemeRenderResult(
            extra_payload={"name": artist, "bio": bio},
            derived_image_path=photo_path,
        )

    def health_detail(self, config: ArtistSpotlightConfig) -> Optional[dict]:
        if self._degraded_reason:
            return {"degraded": True, "reason": self._degraded_reason}
        return None

    def client_assets(self, config: ArtistSpotlightConfig) -> ThemeClientAssets:
        corner = config.corner if config.corner in _VALID_CORNERS else "bottom-left"
        css = f"""
    #theme-artist-spotlight {{
      position: absolute; width: {config.size_vw}vw;
      opacity: 0; transition: opacity 0.8s ease-in-out;
      z-index: 2; font-family: sans-serif; color: #fff; text-align: center;
      text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
    }}
    #theme-artist-spotlight.visible {{ opacity: 1; }}
    #theme-artist-spotlight.corner-bottom-right {{ bottom: 2vh; right: 2vw; }}
    #theme-artist-spotlight.corner-bottom-left  {{ bottom: 2vh; left: 2vw; }}
    #theme-artist-spotlight.corner-top-right    {{ top: 2vh; right: 2vw; }}
    #theme-artist-spotlight.corner-top-left     {{ top: 2vh; left: 2vw; }}
    #theme-artist-spotlight.corner-center       {{
      top: 50%; left: 50%; transform: translate(-50%, -50%);
    }}
    #theme-artist-spotlight img {{
      width: 100%; aspect-ratio: 1 / 1; object-fit: cover;
      border-radius: 50%; display: block;
    }}
    #theme-artist-spotlight .name {{
      font-size: 1.2vw; font-weight: 700; margin-top: 0.6vh;
    }}
    #theme-artist-spotlight .bio {{
      font-size: 0.75vw; opacity: 0.75; margin-top: 0.3vh;
      display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
      overflow: hidden;
    }}
"""
        js = f"""
    (function() {{
      var card = document.createElement('div');
      card.id = 'theme-artist-spotlight';
      card.className = 'theme-artist-spotlight corner-{corner}';
      var img = document.createElement('img');
      img.alt = '';
      var name = document.createElement('div');
      name.className = 'name';
      var bio = document.createElement('div');
      bio.className = 'bio';
      card.appendChild(img);
      card.appendChild(name);
      card.appendChild(bio);
      document.getElementById('theme-layer').appendChild(card);

      window.themeHandlers.artist_spotlight = function(data) {{
        if (!data || !data.image) {{
          card.classList.remove('visible');
          return;
        }}
        img.src = data.image;
        name.textContent = data.name || '';
        bio.textContent = data.bio || '';
        bio.style.display = data.bio ? '-webkit-box' : 'none';
        card.classList.add('visible');
      }};
    }})();
"""
        return ThemeClientAssets(css=css, js=js)
