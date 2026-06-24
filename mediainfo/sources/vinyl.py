"""Turntable "now playing" source, via the vinyl_recognizer service.

Polls a `vinyl_recognizer` instance (running on the machine the Behringer
UCA202 is connected to) for the most recently recognized track from the
turntable's line-in.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from mediainfo.config import VinylConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# Matches vinyl_recognizer's recognition_provider values (and its
# "local_folder" fallback tag) to a human-readable label for the artwork
# source, rather than hardcoding one provider's name.
_PROVIDER_LABELS = {
    "audd": "AudD",
    "acrcloud": "ACRCloud",
    "acoustid": "AcoustID",
    "shazam": "Shazam",
    "vibra": "vibra",
    "local_folder": "local folder",
}


class VinylSource(MediaSource):
    name = "vinyl"

    def __init__(self, config: VinylConfig):
        self.config = config
        self._url = f"http://{config.host}:{config.port}/now-playing"

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
        try:
            response = requests.get(self._url, timeout=5)
            response.raise_for_status()
            data = response.json()
        except Exception:
            logger.exception("Vinyl source error")
            self.last_poll_failed = True
            return None

        title = data.get("title", "")
        if not title:
            return None

        images = []
        artwork_url = data.get("artwork_url")
        if artwork_url:
            provider = data.get("provider", "")
            label = _PROVIDER_LABELS.get(provider, provider or "vinyl_recognizer")
            images.append(Artwork(url=artwork_url, label=f"Album art ({label})"))

        return NowPlaying(
            source=self.name,
            media_type="music",
            title=title,
            subtitle=data.get("artist", ""),
            album=data.get("album", ""),
            images=images,
        )
