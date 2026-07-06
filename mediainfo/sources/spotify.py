"""Spotify 'now playing' source via the Web API."""

from __future__ import annotations

import logging
from typing import Optional

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from mediainfo.config import SpotifyConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# current_playback() (GET /me/player) needs the broader "playback-state"
# scope, unlike the narrower current_user_playing_track() this replaced -
# a token cached under the old "user-read-currently-playing" scope alone
# doesn't carry this, hence the explicit scope check in get_now_playing()
# below rather than just letting a mismatched token 403 unhelpfully.
SCOPE = "user-read-playback-state"


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
        self.last_poll_failed = False
        try:
            token_info = self._auth.get_cached_token()
            if token_info is None:
                logger.warning(
                    "Spotify: no cached token at %s — "
                    "run 'python -m mediainfo auth spotify' to authorize",
                    self._config.cache_path,
                )
                self.last_poll_failed = True
                return None

            granted_scopes = (token_info.get("scope") or "").split()
            if "user-read-playback-state" not in granted_scopes:
                logger.warning(
                    "Spotify: cached token at %s was authorized without the "
                    "'user-read-playback-state' scope (needed for device/"
                    "progress info) — run 'python -m mediainfo auth spotify' "
                    "again to refresh it",
                    self._config.cache_path,
                )
                self.last_poll_failed = True
                return None

            client = spotipy.Spotify(auth=token_info["access_token"])
            # current_playback() (GET /me/player) rather than the narrower
            # current_user_playing_track() (GET /me/player/currently-playing):
            # same track info, plus which device is playing and progress/
            # duration - Spotify Connect's state is account-wide regardless
            # of which endpoint is used, so this doesn't change *what* can
            # be detected, only how much detail comes back about it.
            result = client.current_playback()

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

            device_name = (result.get("device") or {}).get("name", "")
            progress_ms = result.get("progress_ms")
            duration_ms = item.get("duration_ms")

            return NowPlaying(
                source=self.name,
                media_type="music",
                title=title,
                subtitle=artist,
                album=album,
                artist=artist,
                device=device_name,
                images=artworks,
                position_seconds=progress_ms / 1000 if progress_ms is not None else None,
                duration_seconds=duration_ms / 1000 if duration_ms is not None else None,
            )
        except Exception:
            logger.exception("Spotify source error")
            self.last_poll_failed = True
            return None
