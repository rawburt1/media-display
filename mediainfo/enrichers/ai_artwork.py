"""AI-generated artwork enricher: optionally generates album-art-style
images from a short mood/genre prompt using a local Stable-Diffusion-
WebUI-API-compatible instance (the AUTOMATIC1111 txt2img REST API,
https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/API - widely
implemented by SD/SDXL forks; whatever checkpoint the user has loaded
determines the actual model, e.g. SD1.5/SDXL/a FLUX-compatible fork).
ComfyUI is NOT supported here - its node-graph workflow submission API is
a fundamentally different shape and would need its own enricher.

Optional and off by default (see AiArtworkConfig.enabled) - it depends on
the user running a compatible instance locally themselves. Image
generation can take a while depending on model/steps/hardware, and this
call happens synchronously within the orchestrator's normal enrichment
step like every other enricher - AiArtworkConfig.timeout_seconds bounds
the worst case, and generated images are cached to disk per song (in
`cache_dir`, passed in by wiring.build_enrichers()) so most plays reuse
the cached file instead of regenerating.

Deliberately builds the prompt from short metadata only (mood, from a
prior TextEnricher's NowPlaying.ai_text if one ran - see
mediainfo/enrichers/ollama_text.py - or a plain genre-based fallback) -
never from NowPlaying.lyrics/synced_lyrics.

Only applies to media_type == "music". The generated image is appended
to NowPlaying.images like any other enriched artwork (not a replacement
for real album art), reusing ImageCache as-is via a `file://` URL
pointing at the already-cached PNG - ImageCache.get_path() returns
`file://` paths directly without re-downloading.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path
from typing import Optional, Union

import requests

from mediainfo.config import AiArtworkConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)


class AiArtworkEnricher(ArtworkEnricher):
    name = "ai_artwork"
    config_class = AiArtworkConfig
    capabilities = frozenset({"cache_dir"})

    def __init__(self, config: AiArtworkConfig, cache_dir: Union[str, Path]):
        self.config = config
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "music":
            return
        artist, title = now_playing.subtitle, now_playing.title
        if not artist or not title:
            return

        key = f"{artist}|{title}|{now_playing.album}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        path = self.cache_dir / f"{digest}.png"

        if not path.exists():
            image_bytes = self._generate(now_playing)
            if image_bytes is None:
                return
            path.write_bytes(image_bytes)

        now_playing.images.append(Artwork(url=f"file://{path}", label="AI-generated artwork"))

    @staticmethod
    def _build_prompt(now_playing: NowPlaying) -> str:
        """Short, non-lyrical prompt: a mood word/phrase (from a prior
        TextEnricher, if one populated NowPlaying.ai_text) plus genre,
        falling back to genre (or just "music") alone when no mood text
        exists yet."""
        mood = now_playing.ai_text.get("mood")
        genre = ", ".join(now_playing.genres) if now_playing.genres else ""
        if mood and genre:
            return f"album cover art, {mood}, {genre}"
        if mood:
            return f"album cover art, {mood}"
        if genre:
            return f"abstract album cover art, {genre}"
        return "abstract album cover art"

    def _generate(self, now_playing: NowPlaying) -> Optional[bytes]:
        prompt = self._build_prompt(now_playing)
        try:
            response = requests.post(
                f"http://{self.config.host}:{self.config.port}/sdapi/v1/txt2img",
                json={
                    "prompt": prompt,
                    "steps": self.config.steps,
                    "width": self.config.width,
                    "height": self.config.height,
                },
                timeout=self.config.timeout_seconds,
            )
            response.raise_for_status()
            images = response.json().get("images") or []
            if not images:
                return None
            image_bytes = base64.b64decode(images[0])
            if not image_bytes:
                # An empty (but present) base64 string decodes to b"" with
                # no exception - writing that to path below would create a
                # permanent 0-byte "cache hit" (see enrich(): `if not
                # path.exists()` never re-generates once the file exists),
                # so every future play of this song would silently reuse
                # broken artwork forever.
                return None
            return image_bytes
        except Exception:
            logger.exception(
                "AI artwork generation failed for %s - %s", now_playing.subtitle, now_playing.title
            )
            return None
