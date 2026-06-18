"""Pixabay video source: fetches portrait video clips via the Pixabay API."""

from __future__ import annotations

import logging
import random

import requests

from mediainfo.video.base import VideoClip, VideoSource

logger = logging.getLogger(__name__)

_PIXABAY_API = "https://pixabay.com/api/videos/"
# Pixabay free-tier cap is 20 results per page.
_MAX_PER_PAGE = 20


class PixabayVideoSource(VideoSource):
    def __init__(self, api_key: str, queries: str, batch_size: int = 15):
        self._api_key = api_key
        self._queries = [q.strip() for q in queries.split(",") if q.strip()]
        self._batch_size = min(batch_size, _MAX_PER_PAGE)

    def get_videos(self) -> list[VideoClip]:
        if not self._queries:
            return []
        query = random.choice(self._queries)
        try:
            resp = requests.get(
                _PIXABAY_API,
                params={
                    "key": self._api_key,
                    "q": query,
                    "video_type": "film",
                    "orientation": "vertical",
                    "per_page": self._batch_size,
                },
                timeout=15,
            )
            resp.raise_for_status()
        except Exception:
            logger.exception("Pixabay video API error (query=%r)", query)
            return []

        clips = []
        for hit in resp.json().get("hits", []):
            url = _best_url(hit.get("videos", {}))
            if url:
                clips.append(VideoClip(url=url, label=f"Pixabay: {query}"))
        logger.info("Pixabay: fetched %d video(s) for query %r", len(clips), query)
        return clips


# Pixabay video sizes in preference order (largest first for quality).
_SIZE_PREFERENCE = ("large", "medium", "small", "tiny")


def _best_url(videos: dict) -> str | None:
    """Return the best portrait mp4 URL from a Pixabay hit's videos dict."""
    # Try to find a portrait (height > width) file first.
    for size in _SIZE_PREFERENCE:
        entry = videos.get(size, {})
        url = entry.get("url")
        w = entry.get("width", 0)
        h = entry.get("height", 0)
        if url and h > w:
            return url
    # Fall back to any available size.
    for size in _SIZE_PREFERENCE:
        url = videos.get(size, {}).get("url")
        if url:
            return url
    return None
