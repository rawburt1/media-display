"""Plex "now playing" source via the Plex Media Server API."""

from __future__ import annotations

import logging
from typing import Optional

import requests

from mediainfo.config import PlexConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# Plex "Guid" providers we know how to map onto the id keys enrichers expect
# (fanart.tv uses tmdb/imdb for movies and tvdb for TV shows).
_GUID_PROVIDERS = {"imdb", "tmdb", "tvdb"}


def resolve_plex_image_url(host: str, port: int, token: str, path: str) -> str:
    """Turn a Plex-relative art path (e.g. "/library/metadata/123/thumb/456")
    into a URL that includes the auth token Plex requires to serve it.
    """
    return f"http://{host}:{port}{path}?X-Plex-Token={token}"


def _parse_guids(item: dict) -> dict:
    ids = {}
    for guid in item.get("Guid", []) or []:
        guid_value = guid.get("id", "")
        if "://" not in guid_value:
            continue
        provider, value = guid_value.split("://", 1)
        if provider in _GUID_PROVIDERS:
            ids[provider] = value
    return ids


class PlexSource(MediaSource):
    config_class = PlexConfig
    name = "plex"

    def __init__(self, config: PlexConfig):
        self.config = config
        self._url = f"http://{config.host}:{config.port}"

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
        try:
            response = requests.get(
                f"{self._url}/status/sessions",
                headers={"X-Plex-Token": self.config.token, "Accept": "application/json"},
                timeout=5,
            )
            response.raise_for_status()
            sessions = response.json().get("MediaContainer", {}).get("Metadata") or []
            if not sessions:
                return None

            item = sessions[0]
            if item.get("Player", {}).get("state") != "playing":
                return None

            plex_type = item.get("type")
            if plex_type == "movie":
                media_type = "movie"
                title = item.get("title", "")
                subtitle = ""
                poster_path = item.get("thumb")
                fanart_path = item.get("art")
            elif plex_type == "episode":
                media_type = "episode"
                title = item.get("grandparentTitle", "")
                season = item.get("parentIndex")
                episode = item.get("index")
                ep_title = item.get("title", "")
                if season is not None and episode is not None:
                    subtitle = f"S{season:02d}E{episode:02d} - {ep_title}"
                else:
                    subtitle = ep_title
                # Prefer the series poster/fanart over the episode's own still/art.
                poster_path = (
                    item.get("grandparentThumb") or item.get("parentThumb") or item.get("thumb")
                )
                fanart_path = item.get("grandparentArt") or item.get("art")
            else:
                media_type = "music"
                title = item.get("title", "")
                subtitle = item.get("grandparentTitle", "")
                # Prefer the album cover over the artist image or track thumbnail.
                poster_path = (
                    item.get("parentThumb") or item.get("grandparentThumb") or item.get("thumb")
                )
                fanart_path = item.get("art")

            images = []
            seen_paths = set()
            for path, label in ((poster_path, "Poster (Plex)"), (fanart_path, "Fanart (Plex)")):
                if not path or path in seen_paths:
                    continue
                seen_paths.add(path)
                image_url = resolve_plex_image_url(
                    self.config.host, self.config.port, self.config.token, path
                )
                images.append(Artwork(url=image_url, label=label))

            return NowPlaying(
                source=self.name,
                media_type=media_type,
                title=title,
                subtitle=subtitle,
                album=item.get("parentTitle", "") if media_type == "music" else "",
                images=images,
                ids=_parse_guids(item),
                season=item.get("parentIndex") if media_type == "episode" else None,
                year=item.get("year") if media_type == "movie" else None,
            )
        except Exception:
            logger.exception("Plex source error")
            self.last_poll_failed = True
            return None
