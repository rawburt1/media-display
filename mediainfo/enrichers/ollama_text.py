"""Ollama-backed AI text enricher: generates short, original text about
the currently playing song - mood, a brief description, a "did you know"
note, and album/artist context - using a local Ollama instance
(https://ollama.com) as the model backend.

Optional and off by default (see OllamaTextConfig.enabled) - it depends
on the user having Ollama running locally with a model already pulled.
Local inference can take several seconds depending on model size/
hardware, and this call happens synchronously within the orchestrator's
normal enrichment step like every other enricher - OllamaTextConfig.
timeout_seconds bounds the worst case, and results are cached per song
(see TextCache) so most plays hit the cache instead of re-generating.

Deliberately never sends lyrics (NowPlaying.lyrics/synced_lyrics) or any
other copyrighted text to the model - only metadata already on NowPlaying
(artist, title, album, genres, year). The prompt explicitly asks for
short, original text *about* the song from that metadata, not a
reproduction or paraphrase of its lyrics.

Only applies to media_type == "music".
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import requests

from mediainfo.config import OllamaTextConfig
from mediainfo.enrichers.text_base import TextEnricher
from mediainfo.models import NowPlaying
from mediainfo.text_cache import TextCache

logger = logging.getLogger(__name__)

_NAMESPACE = "ollama_text"

# The four short text fields this enricher can add to NowPlaying.ai_text.
_FIELDS = ("mood", "description", "fun_fact", "context")

_PROMPT_TEMPLATE = """You are writing short, tasteful text to accompany a "now playing" display.
Using ONLY the metadata below - never assume, invent, or reproduce any lyrics - write:
- "mood": the likely mood/atmosphere of this song, a few words to one short sentence.
- "description": a brief, one-sentence description of the song or its style.
- "fun_fact": a short "did you know"-style note about the song, artist, or album - if you don't know anything specific and verifiable, write a short, clearly general remark instead of inventing a false fact.
- "context": one short sentence of context about the album or artist.

Metadata:
  Artist: {artist}
  Title: {title}
  Album: {album}
  Genres: {genres}
  Year: {year}

Respond with ONLY a JSON object with exactly these four string keys: mood, description, fun_fact, context."""


class OllamaTextEnricher(TextEnricher):
    name = "ollama_text"
    config_class = OllamaTextConfig

    def __init__(self, config: OllamaTextConfig, cache: Optional[TextCache] = None):
        self.config = config
        self.cache = cache

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "music":
            return
        artist, title = now_playing.subtitle, now_playing.title
        if not artist or not title:
            return

        cache_key = f"{artist}|{title}|{now_playing.album}"
        if self.cache is not None:
            cached = self.cache.get(_NAMESPACE, cache_key)
            if cached is not None:
                self._apply(now_playing, cached)
                return

        result = self._generate(now_playing)
        if result is None:
            return
        if self.cache is not None:
            self.cache.set(_NAMESPACE, cache_key, result)
        self._apply(now_playing, result)

    @staticmethod
    def _apply(now_playing: NowPlaying, result: dict) -> None:
        for field in _FIELDS:
            value = result.get(field)
            if isinstance(value, str) and value:
                now_playing.ai_text[field] = value

    def _generate(self, now_playing: NowPlaying) -> Optional[dict]:
        prompt = _PROMPT_TEMPLATE.format(
            artist=now_playing.subtitle,
            title=now_playing.title,
            album=now_playing.album or "unknown",
            genres=", ".join(now_playing.genres) or "unknown",
            year=now_playing.year or "unknown",
        )
        try:
            response = requests.post(
                f"http://{self.config.host}:{self.config.port}/api/generate",
                json={
                    "model": self.config.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
                timeout=self.config.timeout_seconds,
            )
            response.raise_for_status()
            parsed = json.loads(response.json().get("response", ""))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            logger.exception(
                "Ollama text generation failed for %s - %s", now_playing.subtitle, now_playing.title
            )
            return None
