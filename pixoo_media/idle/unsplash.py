"""Unsplash idle wallpaper source.

Picks a random photo matching one of the configured search queries to show
on outputs while nothing is playing. Requires a free Access Key from
https://unsplash.com/oauth/applications.
"""

from __future__ import annotations

import logging
import random
from typing import Optional

import requests

from pixoo_media.config import UnsplashWallpaperConfig
from pixoo_media.idle.base import IdleWallpaperSource
from pixoo_media.models import Artwork

logger = logging.getLogger(__name__)

_RANDOM_PHOTO_URL = "https://api.unsplash.com/photos/random"


class UnsplashWallpaperSource(IdleWallpaperSource):
    def __init__(self, config: UnsplashWallpaperConfig):
        self.config = config
        self.rotation_interval_seconds = config.rotation_interval_seconds
        self.queries = [q.strip() for q in config.queries.split(",") if q.strip()]

    def get_wallpaper(self) -> Optional[Artwork]:
        params = {}
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
            logger.exception("Failed to fetch wallpaper from Unsplash")
            return None

        url = data.get("urls", {}).get("regular")
        if not url:
            return None

        description = data.get("description") or data.get("alt_description") or ""
        label = f"Unsplash: {description}" if description else "Unsplash"
        return Artwork(url=url, label=label)
