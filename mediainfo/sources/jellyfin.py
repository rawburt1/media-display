"""Jellyfin and Emby 'now playing' sources via the Sessions API.

Both servers expose an almost identical REST API (they share the MediaBrowser
lineage), so a single implementation covers both.  Auth uses the api_key query
parameter, which is supported by all Jellyfin and Emby versions.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from mediainfo.config import EmbyConfig, JellyfinConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)


def _image_url(base: str, item_id: str, image_type: str, api_key: str) -> str:
    return f"{base}/Items/{item_id}/Images/{image_type}?api_key={api_key}"


def _parse_ids(provider_ids: Optional[dict]) -> dict:
    """Lower-case the provider keys that enrichers expect."""
    mapping = {
        "Tmdb": "tmdb",
        "Imdb": "imdb",
        "Tvdb": "tvdb",
        "MusicBrainzAlbum": "musicbrainzalbum",
        "MusicBrainzArtist": "musicbrainzartist",
    }
    return {mapping[k]: v for k, v in (provider_ids or {}).items() if k in mapping and v}


class _MediaServerSource(MediaSource):
    """Shared implementation for Jellyfin and Emby."""

    def __init__(self, host: str, port: int, api_key: str) -> None:
        self._base = f"http://{host}:{port}"
        self._api_key = api_key

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
        try:
            resp = requests.get(
                f"{self._base}/Sessions",
                params={"api_key": self._api_key},
                timeout=5,
            )
            resp.raise_for_status()
            for session in resp.json():
                item = session.get("NowPlayingItem")
                if not item:
                    continue
                if session.get("PlayState", {}).get("IsPaused", False):
                    continue
                return self._parse_item(item)
            return None
        except Exception:
            self.log_poll_error(logger, "%s source error", self.name)
            self.last_poll_failed = True
            return None

    def _parse_item(self, item: dict) -> NowPlaying:
        item_type = item.get("Type", "")
        item_id = item.get("Id", "")
        image_tags = item.get("ImageTags") or {}
        backdrop_tags = item.get("BackdropImageTags") or []

        if item_type == "Movie":
            return self._parse_movie(item, item_id, image_tags, backdrop_tags)
        if item_type == "Episode":
            return self._parse_episode(item, item_id, image_tags, backdrop_tags)
        return self._parse_audio(item, item_id, image_tags)

    def _parse_movie(
        self, item: dict, item_id: str, image_tags: dict, backdrop_tags: list
    ) -> NowPlaying:
        images = []
        if image_tags.get("Primary"):
            images.append(
                Artwork(
                    url=_image_url(self._base, item_id, "Primary", self._api_key),
                    label=f"Poster ({self.name})",
                )
            )
        if backdrop_tags:
            images.append(
                Artwork(
                    url=_image_url(self._base, item_id, "Backdrop", self._api_key),
                    label=f"Fanart ({self.name})",
                )
            )
        return NowPlaying(
            source=self.name,
            media_type="movie",
            title=item.get("Name", ""),
            subtitle="",
            images=images,
            ids=_parse_ids(item.get("ProviderIds")),
            year=item.get("ProductionYear"),
        )

    def _parse_episode(
        self, item: dict, item_id: str, image_tags: dict, backdrop_tags: list
    ) -> NowPlaying:
        season = item.get("ParentIndexNumber")
        episode = item.get("IndexNumber")
        ep_name = item.get("Name", "")
        subtitle = (
            f"S{season:02d}E{episode:02d} - {ep_name}"
            if (season is not None and episode is not None)
            else ep_name
        )

        series_id = item.get("SeriesId")
        images = []

        # Prefer the series-level poster; fall back to the episode's own primary.
        if series_id and item.get("SeriesPrimaryImageTag"):
            images.append(
                Artwork(
                    url=_image_url(self._base, series_id, "Primary", self._api_key),
                    label=f"Poster ({self.name})",
                )
            )
        elif image_tags.get("Primary"):
            images.append(
                Artwork(
                    url=_image_url(self._base, item_id, "Primary", self._api_key),
                    label=f"Poster ({self.name})",
                )
            )

        # Parent backdrop (series fanart) is preferred over any episode backdrop.
        parent_backdrop_id = item.get("ParentBackdropItemId")
        parent_backdrop_tags = item.get("ParentBackdropImageTags") or []
        if parent_backdrop_id and parent_backdrop_tags:
            images.append(
                Artwork(
                    url=_image_url(self._base, parent_backdrop_id, "Backdrop", self._api_key),
                    label=f"Fanart ({self.name})",
                )
            )
        elif backdrop_tags:
            images.append(
                Artwork(
                    url=_image_url(self._base, item_id, "Backdrop", self._api_key),
                    label=f"Fanart ({self.name})",
                )
            )

        return NowPlaying(
            source=self.name,
            media_type="episode",
            title=item.get("SeriesName", ""),
            subtitle=subtitle,
            images=images,
            ids=_parse_ids(item.get("ProviderIds")),
            season=season,
        )

    def _parse_audio(self, item: dict, item_id: str, image_tags: dict) -> NowPlaying:
        subtitle = item.get("AlbumArtist", "") or next(iter(item.get("Artists") or []), "")
        album_id = item.get("AlbumId")
        images = []

        # Prefer the album's primary image over the track's own thumbnail.
        if album_id and item.get("AlbumPrimaryImageTag"):
            images.append(
                Artwork(
                    url=_image_url(self._base, album_id, "Primary", self._api_key),
                    label=f"Album art ({self.name})",
                )
            )
        elif image_tags.get("Primary"):
            images.append(
                Artwork(
                    url=_image_url(self._base, item_id, "Primary", self._api_key),
                    label=f"Album art ({self.name})",
                )
            )

        return NowPlaying(
            source=self.name,
            media_type="music",
            title=item.get("Name", ""),
            subtitle=subtitle,
            album=item.get("Album", ""),
            images=images,
            ids=_parse_ids(item.get("ProviderIds")),
        )


class JellyfinSource(_MediaServerSource):
    config_class = JellyfinConfig
    name = "jellyfin"

    def __init__(self, config: JellyfinConfig) -> None:
        super().__init__(config.host, config.port, config.api_key)


class EmbySource(_MediaServerSource):
    config_class = EmbyConfig
    name = "emby"

    def __init__(self, config: EmbyConfig) -> None:
        super().__init__(config.host, config.port, config.api_key)
