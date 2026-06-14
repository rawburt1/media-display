"""Kodi "now playing" source via the JSON-RPC API."""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote

import requests

from pixoo_media.config import KodiConfig
from pixoo_media.models import Artwork, NowPlaying
from pixoo_media.sources.base import MediaSource

logger = logging.getLogger(__name__)

_ITEM_PROPERTIES = [
    "title",
    "showtitle",
    "season",
    "episode",
    "artist",
    "art",
    "thumbnail",
    "uniqueid",
]


def resolve_kodi_image_url(host: str, port: int, art_path: str) -> str:
    """Turn a Kodi VFS art path (e.g. "image://http%3a%2f%2f.../") into a
    URL that Kodi's web server will serve over plain HTTP.
    """
    return f"http://{host}:{port}/image/{quote(art_path, safe='')}"


class KodiSource(MediaSource):
    name = "kodi"

    def __init__(self, config: KodiConfig):
        self.config = config
        self._url = f"http://{config.host}:{config.port}/jsonrpc"
        self._auth = (config.username, config.password) if config.username else None

    def _rpc(self, method: str, params: Optional[dict] = None):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        response = requests.post(self._url, json=payload, auth=self._auth, timeout=5)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"Kodi RPC error: {data['error']}")
        return data.get("result")

    def get_now_playing(self) -> Optional[NowPlaying]:
        try:
            players = self._rpc("Player.GetActivePlayers")
            if not players:
                return None

            player_id = players[0]["playerid"]
            result = self._rpc(
                "Player.GetItem",
                {"playerid": player_id, "properties": _ITEM_PROPERTIES},
            )
            item = result.get("item", {})

            kodi_type = item.get("type")
            if kodi_type == "movie":
                media_type = "movie"
                title = item.get("title", "")
                subtitle = ""
            elif kodi_type == "episode":
                media_type = "episode"
                title = item.get("showtitle", "")
                season = item.get("season")
                episode = item.get("episode")
                ep_title = item.get("title", "")
                if season is not None and episode is not None:
                    subtitle = f"S{season:02d}E{episode:02d} - {ep_title}"
                else:
                    subtitle = ep_title
            else:
                media_type = "music"
                title = item.get("title", "")
                artists = item.get("artist") or []
                subtitle = artists[0] if artists else ""

            art = item.get("art") or {}
            art_path = art.get("poster") or art.get("thumb") or item.get("thumbnail")
            images = []
            if art_path:
                image_url = resolve_kodi_image_url(self.config.host, self.config.port, art_path)
                images.append(Artwork(url=image_url, auth=self._auth, label="Poster (Kodi)"))

            return NowPlaying(
                source=self.name,
                media_type=media_type,
                title=title,
                subtitle=subtitle,
                images=images,
                ids=dict(item.get("uniqueid") or {}),
                season=item.get("season") if media_type == "episode" else None,
            )
        except Exception:
            logger.exception("Kodi source error")
            return None
