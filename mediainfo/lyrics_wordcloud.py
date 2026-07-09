"""Lyrics word-cloud generator: builds a word-cloud image from a track's
full lyrics text, colored from its album art.

Two mask modes (see `generate()`):
  - no mask: a plain rectangular canvas, words colored from a small
    palette of the album art's own dominant colors (quantized, picked
    with a bias toward the more prevalent ones) - the album art sets the
    color scheme, but the cloud's shape is independent of it. This is the
    only mode MediaDataStore.get_track_wordcloud actually uses (see
    below) - reliably legible regardless of a given album cover's tonal
    range.
  - masked: the album art itself is used as WordCloud's `mask`, and each
    word is colored directly from the album art's own pixels at the
    position it landed - the `wordcloud` package's own "image-colored
    word cloud" recipe (see its ImageColorGenerator). CAUTION: WordCloud
    only excludes a pixel that is *exactly* pure white (255, 255, 255) -
    real (photographic, JPEG-compressed) album art essentially never
    contains one, so in practice this mode rarely excludes anything and
    ends up filling the full canvas just like no-mask, only differently
    colored. Kept for callers that want the image-colored recipe anyway;
    not used by the live pipeline.

Wired into the live enrichment pipeline via
mediainfo/media_data_store.py's get_track_wordcloud (non-masked only),
called from mediainfo/enrichers/mediadata.py behind
enrichers.mediadata.wordcloud.enabled - reads lyrics (.lrc) and album art
that MediaDataStore has already cached to disk.

Requires the `wordcloud` package (see requirements.txt) - pulls in
matplotlib as a real dependency, unlike the rest of this project's fairly
lean requirements list, since reimplementing word-cloud layout/collision
packing from scratch isn't worth it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

from PIL import Image
from wordcloud import STOPWORDS, ImageColorGenerator, WordCloud

from mediainfo.colors import dominant_colors

_TIMESTAMP_RE = re.compile(r"^\[\d+:\d+(?:\.\d+)?\]\s*")

_DEFAULT_SIZE = 800


def strip_lrc_timestamps(lrc_text: str) -> str:
    """Plain lyrics text from a .lrc file's contents - drops each line's
    leading [mm:ss.xx] timestamp (plain-lyrics fallback files, which have
    none, pass through unchanged), so WordCloud's own tokenizer sees
    normal words rather than being thrown off by the bracketed prefixes.
    """
    lines = []
    for line in lrc_text.splitlines():
        line = _TIMESTAMP_RE.sub("", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _palette_color_func(colors: List[Tuple[int, int, int]]):
    """A WordCloud `color_func` that randomly picks among `colors`,
    weighted toward the earlier (more dominant) entries - gives the
    no-mask word cloud the album art's color scheme even though, unlike
    the masked variant, there's no "position in the art" for an unmasked
    layout to sample a color from directly."""
    weights = list(range(len(colors), 0, -1))
    total = sum(weights)

    def color_func(word=None, font_size=None, position=None, orientation=None,
                    font_path=None, random_state=None):
        rnd = random_state if random_state is not None else _module_random_state()
        pick = rnd.randint(0, total)
        cumulative = 0
        for color, weight in zip(colors, weights):
            cumulative += weight
            if pick < cumulative:
                return "rgb({}, {}, {})".format(*color)
        return "rgb({}, {}, {})".format(*colors[-1])

    return color_func


def _module_random_state():
    import numpy as np

    return np.random.mtrand._rand


def generate(
    lyrics_text: str,
    album_art_path: Path,
    out_path: Path,
    *,
    use_mask: bool,
    width: int = _DEFAULT_SIZE,
    height: int = _DEFAULT_SIZE,
) -> None:
    """Render a word cloud for `lyrics_text` (a raw .lrc file's contents,
    timestamps and all) to `out_path`, as a transparent-background PNG
    (matching the web output's dark page background - see
    outputs/templates/web/index.html). `album_art_path` supplies the
    color scheme in both modes, and the mask shape itself when
    `use_mask` is True.
    """
    plain = strip_lrc_timestamps(lyrics_text)
    album_art = Image.open(album_art_path).convert("RGB")

    common = dict(
        width=width,
        height=height,
        mode="RGBA",
        background_color=None,
        stopwords=STOPWORDS,
    )

    if use_mask:
        import numpy as np

        mask_image = album_art.resize((width, height))
        mask_array = np.array(mask_image)
        wc = WordCloud(mask=mask_array, **common).generate(plain)
        wc = wc.recolor(color_func=ImageColorGenerator(mask_array))
    else:
        colors = dominant_colors(album_art)
        wc = WordCloud(color_func=_palette_color_func(colors), **common).generate(plain)

    wc.to_file(str(out_path))
