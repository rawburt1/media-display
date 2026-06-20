"""Kodi "now playing" source via the JSON-RPC API."""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote

import requests

from mediainfo.config import KodiConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

_ITEM_PROPERTIES = [
    "title",
    "showtitle",
    "season",
    "episode",
    "year",
    "artist",
    "album",
    "art",
    "thumbnail",
    "uniqueid",
    "tvshowid",
    "musicbrainzalbumid",
    "musicbrainzalbumartistid",
    "musicbrainzartistid",
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
        payload: dict = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        response = requests.post(self._url, json=payload, auth=self._auth, timeout=5)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"Kodi RPC error: {data['error']}")
        return data.get("result")

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
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

            art = item.get("art") or {}

            kodi_type = item.get("type")
            if kodi_type == "movie":
                media_type = "movie"
                title = item.get("title", "")
                subtitle = ""
                poster_path = art.get("poster") or art.get("thumb") or item.get("thumbnail")
                fanart_path = art.get("fanart")
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
                # Prefer the series poster/fanart over the episode's own thumb/art.
                poster_path = (
                    art.get("tvshow.poster")
                    or art.get("season.poster")
                    or art.get("poster")
                    or art.get("thumb")
                    or item.get("thumbnail")
                )
                fanart_path = art.get("tvshow.fanart") or art.get("season.fanart") or art.get("fanart")
            else:
                media_type = "music"
                title = item.get("title", "")
                artists = item.get("artist") or []
                subtitle = artists[0] if artists else ""
                poster_path = art.get("thumb") or item.get("thumbnail")
                fanart_path = art.get("fanart")

            images = []
            seen_paths = set()
            for path, label in ((poster_path, "Poster (Kodi)"), (fanart_path, "Fanart (Kodi)")):
                if not path or path in seen_paths:
                    continue
                seen_paths.add(path)
                image_url = resolve_kodi_image_url(self.config.host, self.config.port, path)
                images.append(Artwork(url=image_url, auth=self._auth, label=label))

            # Episode "uniqueid" entries identify the episode itself, but
            # enrichers (fanart.tv, thetvdb.com) need the series' ids.
            ids = dict(item.get("uniqueid") or {})
            if kodi_type == "episode":
                ids = self._get_tvshow_ids(item.get("tvshowid")) or ids
            elif media_type == "music":
                artist_ids = item.get("musicbrainzalbumartistid") or item.get("musicbrainzartistid") or []
                album_id = item.get("musicbrainzalbumid")
                if artist_ids and album_id:
                    ids = {"musicbrainzartist": artist_ids[0], "musicbrainzalbum": album_id}

            return NowPlaying(
                source=self.name,
                media_type=media_type,
                title=title,
                subtitle=subtitle,
                album=item.get("album", "") if media_type == "music" else "",
                images=images,
                ids=ids,
                season=item.get("season") if media_type == "episode" else None,
                year=item.get("year") if media_type == "movie" else None,
            )
        except Exception:
            logger.exception("Kodi source error")
            self.last_poll_failed = True
            return None

    def _get_tvshow_ids(self, tvshowid: Optional[int]) -> Optional[dict]:
        if tvshowid is None:
            return None
        try:
            result = self._rpc(
                "VideoLibrary.GetTVShowDetails",
                {"tvshowid": tvshowid, "properties": ["uniqueid"]},
            )
            return dict(result.get("tvshowdetails", {}).get("uniqueid") or {}) or None
        except Exception:
            logger.exception("Kodi tvshow lookup error")
            return None
