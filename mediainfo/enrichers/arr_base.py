"""Shared plumbing for the Sonarr/Radarr/Lidarr enrichers, which all match
the playing item against a self-hosted *Arr instance's own library (the
movies/shows/artists you actually track) rather than a public catalog.

Subclasses provide just their own field extraction (network/genres for
Sonarr/Radarr, discography for Lidarr) and image labels; the HTTP plumbing
(the `X-Api-Key` GET wrapper), the "match by exact title, casefolded"
fallback lookup, and the "append a cover-type image if not already present"
logic are identical across all three and live here.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

import requests

from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying


class ArrEnricher(ArtworkEnricher):
    # Overridden by LidarrEnricher, which is on the v1 API - Sonarr/Radarr
    # are both on v3.
    _STATUS_PATH = "/api/v3/system/status"

    def __init__(self, config: Any):
        self.config = config
        self._base = f"http://{config.host}:{config.port}"

    def test_connection(self) -> Tuple[bool, str]:
        try:
            self._get(self._STATUS_PATH)
            return True, "Connected successfully"
        except Exception as exc:
            return False, f"Error: {exc}"

    def _get(self, path: str, params: Optional[dict] = None) -> Optional[Any]:
        response = requests.get(
            f"{self._base}{path}",
            params=params,
            headers={"X-Api-Key": self.config.api_key},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _find_by_exact_title(items: Iterable[dict], title: str, title_field: str) -> Optional[dict]:
        """Return the first item whose `title_field` casefold-matches
        `title`, or None - the shared fallback used once an id-based lookup
        comes up empty."""
        if not title:
            return None
        target = title.strip().casefold()
        for item in items:
            if (item.get(title_field) or "").strip().casefold() == target:
                return item
        return None

    @staticmethod
    def _image_url(images: List[dict], cover_type: str) -> Optional[str]:
        return next(
            (
                img.get("remoteUrl") or img.get("url")
                for img in images
                if img.get("coverType") == cover_type
            ),
            None,
        )

    @classmethod
    def _append_image(
        cls, now_playing: NowPlaying, images: List[dict], cover_type: str, label: str
    ) -> None:
        url = cls._image_url(images, cover_type)
        if url and not any(image.url == url for image in now_playing.images):
            now_playing.images.append(Artwork(url=url, label=label))
