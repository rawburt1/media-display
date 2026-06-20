"""PlayStation 5 "now playing" source via PSNAWP (PlayStation Network API
Wrapper for Python).

Reads the authenticated account's own PSN presence - the same "currently
playing <game>" info shown to friends - rather than talking to the console
directly, so no console-side pairing or network access to it is needed.

Requires a free "npsso" cookie (see config.example.yaml for how to get
one). PSNAWP's underlying HTTP calls don't expose a timeout override at
the level used here, unlike every other source's direct `requests` calls -
a genuinely unreachable psn.com would hang this source's poll rather than
failing fast, since that's not something this module can control.
"""

from __future__ import annotations

import logging
from typing import Optional

from psnawp_api import PSNAWP
from psnawp_api.models import User

from mediainfo.config import Ps5Config
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# Only report games launched on PS5 - the account's presence can list a
# game from another platform (PS4, PSPC) if that's what was last played.
_PLATFORM = "PS5"


class Ps5Source(MediaSource):
    name = "ps5"

    def __init__(self, config: Ps5Config):
        self.config = config
        self._psnawp = PSNAWP(config.npsso)
        self._client = self._psnawp.me()
        # Resolved lazily on first poll (requires its own request) rather
        # than here, so a bad/expired npsso cookie fails get_now_playing()
        # the same way any other source's connection error does, instead
        # of raising out of the constructor.
        self._user: Optional[User] = None

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
        try:
            if self._user is None:
                self._user = self._psnawp.user(online_id=self._client.online_id)

            presence = self._user.get_presence().get("basicPresence") or {}
            games = presence.get("gameTitleInfoList") or []
            game = next(
                (g for g in games if (g.get("launchPlatform") or g.get("format")) == _PLATFORM),
                None,
            )
            if game is None:
                return None

            return self._parse_game(game)
        except Exception:
            logger.exception("PS5 source error")
            self.last_poll_failed = True
            return None

    @staticmethod
    def _parse_game(game: dict) -> NowPlaying:
        images = []
        image_url = game.get("conceptIconUrl") or game.get("npTitleIconUrl")
        if image_url:
            images.append(Artwork(url=image_url, label="Poster (PS5)"))

        return NowPlaying(
            source="ps5",
            media_type="game",
            title=game.get("titleName", "") or "",
            images=images,
        )
