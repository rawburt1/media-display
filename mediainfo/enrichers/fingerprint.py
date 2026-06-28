"""Fingerprint enricher: fills in missing artist/track info for music
sources that know something is playing but can't identify it (e.g. internet
radio, a stream without embedded metadata).

Reads the latest recognition result from a running vinyl_recognizer instance
(/now-playing endpoint). The vinyl_recognizer's background loop continuously
samples audio and identifies tracks via ACRCloud, Shazam, AuDD, etc. - this
enricher simply bridges that result into the mediainfo pipeline.

Only activates for music items where the artist (subtitle) is unknown: if a
source already knows who is playing there's nothing for fingerprinting to add.
Results are accepted only if they were recognized within `max_age_seconds`,
to avoid applying a stale identification from a song that finished long ago.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from mediainfo.config import FingerprintConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)


class FingerprintEnricher(ArtworkEnricher):
    def __init__(self, config: FingerprintConfig):
        self.config = config
        self._url = f"http://{config.host}:{config.port}/now-playing"

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "music":
            return
        if now_playing.subtitle:
            return

        result = self._fetch()
        if not result:
            return

        if not now_playing.subtitle and result.get("artist"):
            now_playing.subtitle = result["artist"]
        if not now_playing.title and result.get("title"):
            now_playing.title = result["title"]
        if not now_playing.album and result.get("album"):
            now_playing.album = result["album"]

        artwork_url = result.get("artwork_url")
        if artwork_url and not any(img.url == artwork_url for img in now_playing.images):
            now_playing.images.append(Artwork(url=artwork_url, label="Album art (fingerprint)"))

    def _fetch(self) -> Optional[dict]:
        try:
            resp = requests.get(self._url, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Fingerprint enricher: vinyl_recognizer unreachable (%s)", e)
            return None

        if not data.get("title"):
            return None

        recognized_at = data.get("recognized_at")
        if recognized_at is not None:
            age = time.time() - recognized_at
            if age > self.config.max_age_seconds:
                logger.debug(
                    "Fingerprint: ignoring stale result (%ds old, max %ds)",
                    int(age), self.config.max_age_seconds,
                )
                return None

        return data
