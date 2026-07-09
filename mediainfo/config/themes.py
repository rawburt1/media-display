"""Config dataclasses for individual Display Theme plugins (see
mediainfo/themes/base.py), nested inside one `themes` output instance's own
`themes:` config (mediainfo.config.outputs.ThemesConfig.themes) - not one of
the top-level `*_CONFIG_TYPES` dicts in mediainfo/config/__init__.py, since a
theme isn't its own output/enricher/source.

Modeled on ENRICHER_CONFIG_TYPES (mediainfo/config/enrichers.py): each theme
is its own `extra="forbid"` pydantic dataclass with `enabled: bool` plus its
own options, collected into THEMES_CONFIG_TYPES and parsed by parse_themes()
- deliberately not transforms.py's parse_pipeline() list-with-a-single-
type-discriminator-key shape, which is permissive (silently drops invalid
entries) and has no config-UI form support.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import pydantic

logger = logging.getLogger(__name__)


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class ColorPaletteConfig:
    # Extracts the current artwork's dominant colors (see
    # mediainfo.colors.dominant_colors) and shows them as a strip of
    # swatches - see mediainfo/themes/color_palette.py. Media-type-
    # agnostic: works for album art, movie posters, or TV episode art
    # alike, since it only needs the resolved artwork image.
    enabled: bool = False
    # How many swatches to show, most-prevalent-color first.
    swatch_count: int = 5
    swatch_position: str = "bottom"  # "bottom" | "top" | "side"


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class BlurredBackgroundConfig:
    # Fills the screen behind the sharp foreground artwork with a heavily
    # blurred, darkened copy of it - see
    # mediainfo/themes/blurred_background.py. Media-type-agnostic (album
    # art, movie posters, TV episode art all work the same way).
    enabled: bool = False
    # Gaussian blur radius, applied after downscaling for speed (and a
    # softer result) - see the module for why downscale-then-blur beats
    # blurring at full resolution.
    blur_radius: int = 40
    # Multiplies brightness after blurring - 1.0 = unchanged, <1 darkens
    # (the default softly dims it so foreground text/art stays readable),
    # >1 brightens.
    brightness: float = 0.6


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class WordCloudConfig:
    # Shows a word cloud built from the currently playing item's text -
    # lyrics for music (reusing MediaDataStore.get_track_wordcloud, the
    # same cached word cloud the web output can already show - see
    # mediainfo/media_data_store.py), or the plot summary for movies/TV
    # (mediainfo.lyrics_wordcloud.generate() directly, since there's no
    # per-item lyrics-shaped cache for that) - see
    # mediainfo/themes/word_cloud.py.
    enabled: bool = False
    corner: str = "bottom-right"  # "bottom-right" | "bottom-left" | "top-right" | "top-left" | "center"
    # Width as a percentage of viewport width (the image is square, so
    # this also sets its height, capped to viewport height).
    size_vw: int = 35


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class GlowConfig:
    # A soft, slowly pulsing colored ambient glow behind the artwork,
    # colored from it by default - see mediainfo/themes/glow.py. The
    # first "continuous/animated" theme (see mediainfo/themes/base.py):
    # the color is computed once per item server-side, but the pulsing
    # itself runs entirely client-side (a CSS animation), no per-tick
    # server work. Media-type-agnostic.
    enabled: bool = False
    # 0-1 - how visible the glow is at its peak.
    intensity: float = 0.6
    # "album_art" (default, uses the artwork's own dominant color) or
    # "fixed" (always fixed_color below, regardless of artwork).
    color_source: str = "album_art"
    fixed_color: str = "#ffffff"
    # Slowly grow/shrink the glow on a loop. When False, it still fades
    # in/out with color changes but doesn't otherwise animate.
    pulse: bool = True


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class KenBurnsConfig:
    # A slow, continuous pan/zoom on the artwork, the classic "Ken Burns"
    # documentary effect - see mediainfo/themes/ken_burns.py. Purely
    # client-side (a CSS animation on a dedicated layer behind the static
    # foreground artwork, in the same letterbox space Blurred Background
    # occupies - never touches the foreground art itself, so it can't
    # fight the existing crossfade transitions). Media-type-agnostic.
    enabled: bool = False
    # Seconds for one full pan/zoom cycle - lower is more noticeable motion.
    duration_seconds: int = 20
    # 0-1 - how visible the animated layer is.
    opacity: float = 0.5


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class ProgressBarConfig:
    # A real-data (not decorative) full-width playback progress border
    # along one screen edge - see mediainfo/themes/progress_bar.py.
    # Media-type-agnostic: shows whenever a source reports both
    # position and duration, regardless of music/movie/episode. A
    # separate, new element from the themes page's own small built-in
    # progress bar - this one is a permanent full-width border, not a
    # replacement for it.
    enabled: bool = False
    # Full-width strip along this screen edge.
    position: str = "bottom"  # "bottom" | "top"
    thickness_px: int = 6
    # A CSS color for the filled portion.
    color: str = "#ffffff"


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class VinylThemeConfig:
    # Shows the album art as a spinning vinyl record - see
    # mediainfo/themes/vinyl.py. Music-only by design (a record-player
    # metaphor has no equivalent for movies/TV): the theme's own
    # prepare() produces nothing outside now_playing.media_type ==
    # "music". Continuous decorative rotation - no real play/pause
    # detection, since no source reports that state today (see the
    # roadmap plan).
    enabled: bool = False
    corner: str = "bottom-left"  # "bottom-right" | "bottom-left" | "top-right" | "top-left" | "center"
    # Diameter as a percentage of the shorter viewport dimension.
    size_vmin: int = 40
    # Seconds for one full rotation - lower spins faster.
    rotation_seconds: int = 8


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class MediaMosaicConfig:
    # A grid of related artwork alongside the current pick - other albums
    # by the artist, other posters/fanart for the item - see
    # mediainfo/themes/media_mosaic.py. Media-type-agnostic: works off
    # whatever NowPlaying.images already holds, regardless of media type.
    # Degrades to a single tile when only one candidate image is
    # available, rather than hiding.
    enabled: bool = False
    corner: str = "top-right"  # "bottom-right" | "bottom-left" | "top-right" | "top-left" | "center"
    # Max width as a percentage of viewport width.
    size_vw: int = 30
    # Cap on how many tiles to include, most-relevant-first (the order
    # NowPlaying.images already has - see enrichers/orchestrator_artwork.py).
    max_tiles: int = 6


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class CastMosaicConfig:
    # A grid of top-billed cast headshots for the current movie/TV item -
    # see mediainfo/themes/cast_mosaic.py. Needs NowPlaying.cast populated
    # (enrichers.tmdb.fetch_cast) - degrades to nothing (reported via
    # health_detail()) when no cast data is available. Movie/TV only -
    # there's no cast concept for music.
    enabled: bool = False
    corner: str = "top-right"  # "bottom-right" | "bottom-left" | "top-right" | "top-left" | "center"
    # Max width as a percentage of viewport width.
    size_vw: int = 30
    # Cap on how many cast members to show - further capped by however
    # many enrichers.tmdb.cast_size actually stored on NowPlaying.cast.
    max_cast: int = 6


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class EqualizerConfig:
    # A purely decorative "now playing audio" bar/wave animation - see
    # mediainfo/themes/equalizer.py. NOT a real audio visualizer: no
    # source in this codebase exposes a PCM/FFT signal to react to, so
    # this is a continuous, self-driven CSS animation that just suggests
    # audio activity while music plays. Music-only by design (like
    # Vinyl), gated on now_playing.media_type == "music".
    enabled: bool = False
    style: str = "bars"  # "bars" | "wave"
    # Full-width strip along this screen edge - all four corners are
    # already claimed by other themes' defaults, see the module docstring
    # in mediainfo/themes/equalizer.py.
    position: str = "bottom"  # "bottom" | "top"
    # Number of bars (style="bars" only).
    bar_count: int = 24
    # 0-1 - how visible the effect is.
    opacity: float = 0.7


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class ArtistSpotlightConfig:
    # A portrait card with the artist's photo (and optionally a short
    # bio) - see mediainfo/themes/artist_spotlight.py. Reuses
    # MediaDataStore.get_artist_photo() (Wikipedia-first/Last.fm-
    # fallback) for the photo and NowPlaying.summary for the bio - both
    # already populated for music by existing enrichers, no new data
    # source needed. Degrades to nothing (reported via health_detail())
    # when no artist photo is found.
    enabled: bool = False
    corner: str = "bottom-left"  # "bottom-right" | "bottom-left" | "top-right" | "top-left" | "center"
    # Max width as a percentage of viewport width.
    size_vw: int = 25
    # Show a short bio snippet (NowPlaying.summary) below the artist name.
    show_bio: bool = True


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class LyricsTickerConfig:
    # A karaoke-style ticker highlighting the current line of time-synced
    # lyrics - see mediainfo/themes/lyrics_ticker.py. Music-only, and
    # needs NowPlaying.synced_lyrics populated (e.g. by text_enrichers.lrclib)
    # - degrades to nothing (reported via health_detail()) when unset.
    enabled: bool = False
    # Full-width strip along this screen edge.
    position: str = "top"  # "top" | "bottom"
    # Show the upcoming line, faded, below the current one.
    show_next_line: bool = True


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class TimelineConfig:
    # A list of the artist's other albums alongside the current one - see
    # mediainfo/themes/timeline.py. Music-only by design (built from
    # NowPlaying.discography, only ever populated for music - see the
    # roadmap plan's media-type coverage table; a TV series episode-list
    # equivalent is explicitly deferred pending a Sonarr-side data source
    # that doesn't exist today).
    #
    # Degrades to showing just the current album when no discography is
    # available (the common case - discography needs the optional,
    # off-by-default Lidarr enricher configured and the artist found in
    # it), rather than hiding - and reports that degraded state via
    # ThemesOutput.health_check() so it's visible on /health instead of
    # silently looking empty.
    enabled: bool = False
    corner: str = "top-left"  # "bottom-right" | "bottom-left" | "top-right" | "top-left" | "center"
    # Cap on how many albums to list.
    max_albums: int = 8


# Registry mapping theme name to its config dataclass type. Adding a new
# theme starts here (and in mediainfo.registries.THEME_CLASSES, and
# mediainfo.themes.<name> for the implementation - see
# mediainfo/registries.py's own docstring for the general pattern this
# mirrors).
THEMES_CONFIG_TYPES: Dict[str, type] = {
    "artist_spotlight": ArtistSpotlightConfig,
    "blurred_background": BlurredBackgroundConfig,
    "cast_mosaic": CastMosaicConfig,
    "color_palette": ColorPaletteConfig,
    "equalizer": EqualizerConfig,
    "glow": GlowConfig,
    "ken_burns": KenBurnsConfig,
    "lyrics_ticker": LyricsTickerConfig,
    "media_mosaic": MediaMosaicConfig,
    "progress_bar": ProgressBarConfig,
    "timeline": TimelineConfig,
    "vinyl": VinylThemeConfig,
    "word_cloud": WordCloudConfig,
}


def parse_themes(raw: Optional[dict]) -> Dict[str, Any]:
    """Parse ThemesConfig.themes' raw dict (one entry per enabled/disabled
    theme, e.g. {"glow": {"enabled": True, "intensity": 0.6}}) into real,
    validated config dataclass instances - same warn-and-skip-unknown-keys
    shape as Config.from_dict()'s enrichers/idle parsing loops, called at
    ThemesOutput construction time (mirrors parse_pipeline(config.transforms)
    being called in WebOutput.__init__ rather than in Config.from_dict()).
    A theme with unrecognised/invalid options raises pydantic.ValidationError
    (extra="forbid" per theme config), same as any other strictly-validated
    config dataclass - unlike transforms.py's permissive style, a typo here
    should fail loudly rather than silently do nothing.
    """
    themes: Dict[str, Any] = {}
    for name, values in (raw or {}).items():
        if name not in THEMES_CONFIG_TYPES:
            logger.warning("Unknown theme %r in config — ignored. Check for typos.", name)
            continue
        themes[name] = THEMES_CONFIG_TYPES[name](**(values or {}))
    return themes
