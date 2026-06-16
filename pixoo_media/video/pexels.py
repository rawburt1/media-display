"""Pexels video source: fetches portrait video clips via the Pexels API."""

from __future__ import annotations

import logging
import random

import requests

from pixoo_media.video.base import VideoClip, VideoSource

logger = logging.getLogger(__name__)

_PEXELS_SEARCH = "https://api.pexels.com/videos/search"


class PexelsVideoSource(VideoSource):
    def __init__(self, api_key: str, queries: str, batch_size: int = 15):
        self._api_key = api_key
        self._queries = [q.strip() for q in queries.split(",") if q.strip()]
        self._batch_size = batch_size

    def get_videos(self) -> list[VideoClip]:
        if not self._queries:
            return []
        query = random.choice(self._queries)
        try:
            resp = requests.get(
                _PEXELS_SEARCH,
                headers={"Authorization": self._api_key},
                params={
                    "query": query,
                    "orientation": "portrait",
                    "per_page": self._batch_size,
                },
                timeout=15,
            )
            resp.raise_for_status()
        except Exception:
            logger.exception("Pexels video API error (query=%r)", query)
            return []

        clips = []
        for video in resp.json().get("videos", []):
            url = _best_mp4_url(video.get("video_files", []))
            if url:
                clips.append(VideoClip(url=url, label=f"Pexels: {query}"))
        logger.info("Pexels: fetched %d video(s) for query %r", len(clips), query)
        return clips


def _best_mp4_url(video_files: list) -> str | None:
    """Return the URL of the best portrait-oriented mp4 from a Pexels video."""
    mp4s = [f for f in video_files if f.get("file_type") == "video/mp4"]
    # Prefer files where height > width (portrait/vertical).
    portrait = [f for f in mp4s if f.get("height", 0) > f.get("width", 0)]
    candidates = portrait or mp4s
    if not candidates:
        return None
    # Within candidates, prefer hd then sd quality.
    for quality in ("hd", "sd"):
        for f in candidates:
            if f.get("quality") == quality:
                return f.get("link")
    return candidates[0].get("link")
