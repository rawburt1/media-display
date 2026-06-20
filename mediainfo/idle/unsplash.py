"""Unsplash idle wallpaper source.

Downloads a batch of random photos matching one of the configured search
queries to show on outputs while nothing is playing. Requires a free Access
Key from https://unsplash.com/oauth/applications.
"""

from __future__ import annotations

import logging
import random
from typing import List

import requests

from mediainfo.config import UnsplashWallpaperConfig
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import Artwork

logger = logging.getLogger(__name__)

_RANDOM_PHOTO_URL = "https://api.unsplash.com/photos/random"


class UnsplashWallpaperSource(IdleWallpaperSource):
    def __init__(self, config: UnsplashWallpaperConfig):
        self.config = config
        self.rotation_interval_seconds = config.rotation_interval_seconds
        self.queries = [q.strip() for q in config.queries.split(",") if q.strip()]

    def get_wallpapers(self) -> List[Artwork]:
        params: dict = {"count": self.config.batch_size}
        if self.queries:
            params["query"] = random.choice(self.queries)

        try:
            response = requests.get(
                _RANDOM_PHOTO_URL,
                params=params,
                headers={
                    "Authorization": f"Client-ID {self.config.access_key}",
                    "Accept-Version": "v1",
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            logger.exception("Failed to fetch wallpapers from Unsplash")
            return []

        if isinstance(data, dict):
            data = [data]

        artworks = []
        for photo in data:
            url = photo.get("urls", {}).get("regular")
            if not url:
                continue

            description = photo.get("description") or photo.get("alt_description") or ""
            label = f"Unsplash: {description}" if description else "Unsplash"
            artworks.append(Artwork(url=url, label=label))

        return artworks
