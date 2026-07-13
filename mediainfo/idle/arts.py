"""Art Institute of Chicago idle wallpaper source.

Shows public-domain artworks from the Art Institute of Chicago's open
collection API (https://api.artic.edu) while nothing is playing. Free, no
API key required.
"""

from __future__ import annotations

import logging
import random
from typing import List

import requests

from mediainfo.config import ArtsWallpaperConfig
from mediainfo.idle.base import IdleWallpaperSource
from mediainfo.models import Artwork
from mediainfo.transforms import parse_pipeline

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.artic.edu/api/v1/artworks/search"
_IMAGE_SIZE = "843,"
# The API doesn't offer a "random" endpoint, so a random page within this
# range is requested each batch instead - wide enough for real variety
# across the collection's tens of thousands of public-domain works without
# needing an extra round-trip just to learn the true page count.
_MAX_PAGE = 100
# The image server enforces hotlink protection - requests without a Referer
# from artic.edu get a 403, even with a normal User-Agent (confirmed against
# the live API). See mediainfo.models.Artwork.headers / cache.py.
_IMAGE_HEADERS = {"Referer": "https://www.artic.edu/"}


class ArtsWallpaperSource(IdleWallpaperSource):
    config_class = ArtsWallpaperConfig
    name = "arts"

    def __init__(self, config: ArtsWallpaperConfig):
        self.config = config
        self.rotation_interval_seconds = config.rotation_interval_seconds
        self.transform_pipeline = parse_pipeline(config.transforms)

    def get_wallpapers(self) -> List[Artwork]:
        params: dict = {
            "fields": "id,title,image_id,artist_display,is_public_domain",
            "query[term][is_public_domain]": "true",
            "limit": self.config.batch_size,
            "page": random.randint(1, _MAX_PAGE),
        }

        try:
            response = requests.get(_SEARCH_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception:
            logger.exception("Failed to fetch artworks from the Art Institute of Chicago")
            return []

        iiif_url = (data.get("config") or {}).get("iiif_url")
        if not iiif_url:
            logger.warning("Art Institute of Chicago response missing config.iiif_url")
            return []

        artworks = []
        for work in data.get("data") or []:
            image_id = work.get("image_id")
            if not image_id or not work.get("is_public_domain"):
                continue

            title = work.get("title") or "Untitled"
            artist = work.get("artist_display") or ""
            label = f"Arts: {title} — {artist}" if artist else f"Arts: {title}"
            artworks.append(
                Artwork(
                    url=f"{iiif_url}/{image_id}/full/{_IMAGE_SIZE}/0/default.jpg",
                    label=label,
                    # The IIIF image server 403s hotlinked requests without
                    # this - confirmed against the live API.
                    headers=_IMAGE_HEADERS,
                )
            )

        return artworks
