"""Spotify 'now playing' source via the Web API."""

from __future__ import annotations

import logging
from typing import Optional

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from pixoo_media.config import SpotifyConfig
from pixoo_media.models import Artwork, NowPlaying
from pixoo_media.sources.base import MediaSource

logger = logging.getLogger(__name__)

SCOPE = "user-read-currently-playing"


class SpotifySource(MediaSource):
    name = "spotify"

    def __init__(self, config: SpotifyConfig):
        self._config = config
        self._auth = SpotifyOAuth(
            client_id=config.client_id,
            client_secret=config.client_secret,
            redirect_uri=config.redirect_uri,
            scope=SCOPE,
            cache_path=config.cache_path,
            open_browser=False,
        )

    def get_now_playing(self) -> Optional[NowPlaying]:
        try:
            token_info = self._auth.get_cached_token()
            if token_info is None:
                logger.warning(
                    "Spotify: no cached token at %s — "
                    "run 'python -m pixoo_media auth spotify' to authorize",
                    self._config.cache_path,
                )
                return None

            client = spotipy.Spotify(auth=token_info["access_token"])
            result = client.current_user_playing_track()

            if not result or not result.get("is_playing"):
                return None

            if result.get("currently_playing_type") != "track":
                return None

            item = result.get("item")
            if not item:
                return None

            title = item.get("name", "")
            if not title:
                return None

            artists = item.get("artists") or []
            artist = artists[0]["name"] if artists else ""
            album_info = item.get("album") or {}
            album = album_info.get("name", "")

            # Spotify returns images sorted largest-first.
            images_data = album_info.get("images") or []
            artworks = []
            if images_data:
                artworks.append(Artwork(url=images_data[0]["url"], label="Album art (Spotify)"))

            return NowPlaying(
                source=self.name,
                media_type="music",
                title=title,
                subtitle=artist,
                album=album,
                images=artworks,
            )
        except Exception:
            logger.exception("Spotify source error")
            return None
