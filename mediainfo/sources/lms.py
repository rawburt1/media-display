"""Logitech Media Server (LMS, formerly SqueezeCenter/SlimServer) "now
playing" source, via its JSON-RPC endpoint (/jsonrpc.js) - a thin wrapper
over LMS's older text-based CLI protocol, where every request is
`{"method": "slim.request", "params": [<playerid>, [<command>, <args...>]]}`
and <playerid> is "" for server-wide (not player-specific) commands.

LMS is inherently multi-player: a single server can have any number of
Squeezebox players/apps connected. If `player_id` isn't configured, this
polls every known player's status and picks one (see _select_player) -
which means a household with several players should set `player_id`
explicitly (see LmsConfig) to avoid an arbitrary one winning.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from mediainfo.config import LmsConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource
from mediainfo.sources.jsonrpc import JsonRpcClient

logger = logging.getLogger(__name__)

# Tags requested on the current playlist track (LMS CLI "status" query) -
# a: artist, l: album, d: duration (seconds), c: coverid (local artwork id,
# used to build /music/<coverid>/cover.jpg), K: artwork_url (a full URL,
# populated instead of coverid for remote streams that provide one).
_STATUS_TAGS = "tags:aldcK"


class LmsSource(MediaSource):
    config_class = LmsConfig
    name = "lms"

    def __init__(self, config: LmsConfig):
        self.config = config
        self._rpc = JsonRpcClient(
            f"http://{config.host}:{config.port}/jsonrpc.js", timeout=config.timeout
        )

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
        try:
            playerid, status = self._select_player()
            if playerid is None or status is None:
                return None
            if status.get("mode") != "play":
                return None

            playlist = status.get("playlist_loop") or []
            track = playlist[0] if playlist else {}

            artist = track.get("artist", "") or ""
            album = track.get("album", "") or ""
            title = track.get("title", "") or ""
            duration = track.get("duration")
            elapsed = status.get("time")

            return NowPlaying(
                source=self.name,
                media_type="music",
                title=title,
                subtitle=artist,
                album=album,
                artist=artist,
                device=status.get("player_name", "") or "",
                images=self._get_artwork(track),
                position_seconds=float(elapsed) if elapsed is not None else None,
                duration_seconds=float(duration) if duration is not None else None,
            )
        except Exception:
            logger.exception("Logitech Media Server source error")
            self.last_poll_failed = True
            return None

    def _select_player(self) -> Tuple[Optional[str], Optional[dict]]:
        """Return (playerid, status) for the player to report on.

        With `player_id` configured, always use that one (whatever its
        state - get_now_playing() itself decides play vs. idle) - and let a
        query failure propagate as a real error (unlike the auto-select
        path below, an explicitly-configured player being unreachable is
        exactly what last_poll_failed exists to signal, not something to
        silently paper over). Otherwise: the first player currently
        playing, else the first paused, else (None, None) - meaning idle,
        same as every other source.
        """
        if self.config.player_id:
            status = self._rpc.call(
                "slim.request", [self.config.player_id, ["status", "-", 1, _STATUS_TAGS]]
            )
            return self.config.player_id, status

        players = self._list_players()
        if not players:
            return None, None

        statuses = [(pid, self._query_status(pid)) for pid in players]
        for pid, status in statuses:
            if status is not None and status.get("mode") == "play":
                return pid, status
        for pid, status in statuses:
            if status is not None and status.get("mode") == "pause":
                return pid, status
        return None, None

    def _list_players(self) -> List[str]:
        try:
            result = self._rpc.call("slim.request", ["", ["players", 0, 100]])
        except Exception:
            logger.exception("LMS player list query failed")
            return []
        return [
            p["playerid"] for p in (result or {}).get("players_loop") or [] if p.get("playerid")
        ]

    def _query_status(self, playerid: str) -> Optional[dict]:
        try:
            return self._rpc.call("slim.request", [playerid, ["status", "-", 1, _STATUS_TAGS]])
        except Exception:
            logger.exception("LMS status query failed for player %s", playerid)
            return None

    def _get_artwork(self, track: dict) -> List[Artwork]:
        artwork_url = track.get("artwork_url")
        if artwork_url:
            if not artwork_url.startswith(("http://", "https://")):
                artwork_url = f"http://{self.config.host}:{self.config.port}{artwork_url}"
            return [Artwork(url=artwork_url, label="Album art (LMS)")]

        coverid = track.get("coverid")
        if coverid:
            url = f"http://{self.config.host}:{self.config.port}/music/{coverid}/cover.jpg"
            return [Artwork(url=url, label="Album art (LMS)")]

        return []
