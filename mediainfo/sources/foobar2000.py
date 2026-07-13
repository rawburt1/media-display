"""foobar2000 "now playing" source.

foobar2000 has no single standard remote-control API of its own, so this
talks to the Beefweb Remote Control plugin
(https://github.com/hyperblast/beefweb) - install and enable it in
foobar2000: File -> Preferences -> Beefweb Remote Control (the plugin adds
this page once installed), then enable the HTTP server there. `api_type`
is kept as an explicit config field for other plugins to be added later,
rather than assuming Beefweb is the only option forever.

Beefweb's metadata model is column-based rather than fixed fields (it's
built on foobar2000's own title-formatting query language) - the
`columns` query param below asks it to evaluate %artist%/%album%/%title%
for the currently playing item, and the response echoes them back in the
same order in `activeItem.columns`.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from mediainfo.config import Foobar2000Config
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# Mirrors every other source: "paused"/"stopped" are treated as idle.
_ACTIVE_STATES = {"playing"}

_COLUMNS = "%artist%,%album%,%title%"


class Foobar2000Source(MediaSource):
    config_class = Foobar2000Config
    name = "foobar2000"

    def __init__(self, config: Foobar2000Config):
        self.config = config
        self._base_url = f"http://{config.host}:{config.port}"

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False

        if self.config.api_type != "beefweb":
            logger.error(
                "foobar2000 source: api_type %r is not supported - only "
                "'beefweb' (https://github.com/hyperblast/beefweb) is "
                "implemented today",
                self.config.api_type,
            )
            self.last_poll_failed = True
            return None

        try:
            response = requests.get(
                f"{self._base_url}/api/player",
                params={"columns": _COLUMNS},
                timeout=self.config.timeout,
            )
            response.raise_for_status()
            player = (response.json() or {}).get("player") or {}

            if player.get("playbackState") not in _ACTIVE_STATES:
                return None

            item = player.get("activeItem") or {}
            columns = item.get("columns") or ["", "", ""]
            artist, album, title = (columns + ["", "", ""])[:3]

            if not title:
                return None

            images = []
            playlist_id = item.get("playlistId")
            index = item.get("index")
            if playlist_id is not None and index is not None:
                images.append(
                    Artwork(
                        url=f"{self._base_url}/api/artwork/{playlist_id}/{index}",
                        label="Artwork (foobar2000)",
                    )
                )

            position = item.get("position")
            duration = item.get("duration")

            return NowPlaying(
                source=self.name,
                media_type="music",
                title=title,
                subtitle=artist,
                album=album,
                artist=artist,
                images=images,
                position_seconds=float(position) if position is not None else None,
                duration_seconds=float(duration) if duration is not None else None,
            )
        except Exception:
            logger.exception("foobar2000 source error")
            self.last_poll_failed = True
            return None
