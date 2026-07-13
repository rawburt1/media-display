"""Pexels idle wallpaper source.

Downloads a batch of stock photos matching one of the configured search
queries to show on outputs while nothing is playing. Requires a free API
key from https://www.pexels.com/api/ - the same key works for
`outputs.video`'s Pexels video clips too, though they're independent
config sections.

Enabling this alongside `idle.unsplash` gives an automatic fallback: each
idle source is fetched independently and merged into one pool (see
idle/composite.py), so if Unsplash is unreachable, Pexels' wallpapers
still populate the pool instead of leaving outputs with nothing.
"""

from __future__ import annotations

import logging
import random
from typing import List

import requests

from mediainfo.config import PexelsWallpaperConfig
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import Artwork

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.pexels.com/v1/search"


class PexelsWallpaperSource(IdleWallpaperSource):
    config_class = PexelsWallpaperConfig
    name = "pexels"

    def __init__(self, config: PexelsWallpaperConfig):
        self.config = config
        self.rotation_interval_seconds = config.rotation_interval_seconds
        self.queries = [q.strip() for q in config.queries.split(",") if q.strip()]

    def get_wallpapers(self) -> List[Artwork]:
        if not self.queries:
            return []
        query = random.choice(self.queries)

        params: dict = {"query": query, "per_page": self.config.batch_size}
        try:
            response = requests.get(
                _SEARCH_URL,
                headers={"Authorization": self.config.api_key},
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            photos = response.json().get("photos", [])
        except Exception:
            logger.exception("Failed to fetch wallpapers from Pexels (query=%r)", query)
            return []

        artworks = []
        for photo in photos:
            url = (photo.get("src") or {}).get("original")
            if not url:
                continue
            label = f"Pexels: {photo.get('alt')}" if photo.get("alt") else "Pexels"
            artworks.append(Artwork(url=url, label=label))

        logger.info("Pexels: fetched %d wallpaper(s) for query %r", len(artworks), query)
        return artworks
