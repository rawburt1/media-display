"""Ulanzi TC001 (AWTRIX3) output: shows "now playing" info as scrolling text.

Unlike the other outputs, this doesn't show any artwork - it pushes a small
"custom app" to AWTRIX3's local HTTP API with a short text description of
what's playing, e.g.:
  - music:   "Artist - Song" (release/version suffixes like "- 2011
              Remaster" or "(Live)" are stripped from the song title)
  - movie:   "Title (Year)"
  - episode: "Show s01e01"

See https://github.com/Blueforcer/awtrix3/blob/main/docs/api.md
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import requests

from mediainfo.cache import ImageCache
from mediainfo.config import UlanziConfig
from mediainfo.display_schedule import DisplaySchedule, ScheduledDisplay
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output

logger = logging.getLogger(__name__)

# Matches the "S01E01 - Episode Title" subtitle format produced by the Kodi
# and Plex sources for episodes.
_EPISODE_SUBTITLE_RE = re.compile(r"^S(\d+)E(\d+)", re.IGNORECASE)

# Words identifying a "version/edition" suffix on a track title (e.g.
# "Comfortably Numb - 2011 Remastered Version", "Money (Live)") that's
# dropped from the title shown on the Ulanzi display.
_VERSION_INFO_KEYWORDS = [
    "mastered",
    "remastered",
    "remaster",
    "restored",
    "digitized",
    "digital transfer",
    "transferred from original tapes",
    "from the original master tapes",
    "tape restoration",
    "noise reduced",
    "de-clicked",
    "de-hissed",
    "remix",
    "mix",
    "version",
    "edition",
    "edit",
    "take",
    "outtake",
    "demo",
    "rehearsal",
    "previously unreleased",
    "live",
    "reissue",
    "original motion picture soundtrack",
    "original cast recording",
    "compilation",
]
_VERSION_INFO_PATTERN = "|".join(_VERSION_INFO_KEYWORDS)

# A trailing "(...)" or "[...]" group containing one of the keywords above,
# e.g. "(2011 Remaster)", "[Live]".
_VERSION_INFO_BRACKET_RE = re.compile(
    rf"\s*[\(\[][^()\[\]]*\b(?:{_VERSION_INFO_PATTERN})\b[^()\[\]]*[\)\]]\s*$",
    re.IGNORECASE,
)
# A trailing "- ..." suffix containing one of the keywords above, e.g.
# " - 2011 Remaster", " - Live".
_VERSION_INFO_DASH_RE = re.compile(
    rf"\s*-\s*[^-]*\b(?:{_VERSION_INFO_PATTERN})\b[^-]*$",
    re.IGNORECASE,
)


def _strip_version_info(title: str) -> str:
    stripped = title
    while True:
        next_stripped = _VERSION_INFO_BRACKET_RE.sub("", stripped).strip()
        next_stripped = _VERSION_INFO_DASH_RE.sub("", next_stripped).strip()
        if next_stripped == stripped:
            break
        stripped = next_stripped

    # Don't return an empty title if stripping consumed everything.
    return stripped or title


class UlanziOutput(Output):
    name = "ulanzi"
    config_class = UlanziConfig
    handles_images = False  # text only; idle wallpaper images are not sent here

    def __init__(self, config: UlanziConfig):
        self.config = config
        self._url = f"http://{config.device_ip}/api/custom"
        self._auth = (config.username, config.password) if config.username else None
        self._last_text: Optional[str] = None
        self._scheduler = ScheduledDisplay(
            DisplaySchedule(config.screen_off_hours, config.brightness_schedule),
            set_power=self._set_power,
            set_brightness=self._set_brightness,
            label=f"Ulanzi {config.device_ip}",
        )

    def on_schedule_tick(self) -> None:
        self._scheduler.tick()

    def _set_power(self, on: bool) -> None:
        response = requests.post(
            f"http://{self.config.device_ip}/api/power",
            json={"power": on},
            auth=self._auth,
            timeout=5,
        )
        response.raise_for_status()

    def _set_brightness(self, level: int) -> None:
        # Only effective while AWTRIX3's own auto-brightness (ABRI) is off
        # - see UlanziConfig.brightness_schedule.
        response = requests.post(
            f"http://{self.config.device_ip}/api/settings",
            json={"BRI": level},
            auth=self._auth,
            timeout=5,
        )
        response.raise_for_status()

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        if now_playing.source == "idle":
            self._set_text(None)

    def on_idle(self) -> None:
        self._set_text(None)

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        self._set_text(self._format(now_playing))

    def _format(self, now_playing: NowPlaying) -> str:
        if now_playing.media_type == "music":
            title = _strip_version_info(now_playing.title)
            if now_playing.subtitle:
                return f"{now_playing.subtitle} - {title}"
            return title

        if now_playing.media_type == "movie":
            if now_playing.year:
                return f"{now_playing.title} ({now_playing.year})"
            return now_playing.title

        if now_playing.media_type == "episode":
            match = _EPISODE_SUBTITLE_RE.match(now_playing.subtitle)
            if match:
                season, episode = match.groups()
                return f"{now_playing.title} s{season}e{episode}"
            if now_playing.subtitle:
                return f"{now_playing.title} - {now_playing.subtitle}"
            return now_playing.title

        return now_playing.title

    def _set_text(self, text: Optional[str]) -> None:
        if text == self._last_text:
            return

        # Deliberately no try/except here - letting connection/HTTP errors
        # propagate lets the orchestrator's _call_output() record them for
        # health/alerting (see orchestrator.py:_call_output). Swallowing
        # them here used to mean a Ulanzi that dropped off the network was
        # silently reported as healthy.
        if text:
            response = requests.post(
                self._url,
                params={"name": self.config.app_name},
                # textCase=2 displays the text as sent, overriding
                # AWTRIX3's default of forcing everything to uppercase.
                json={"text": text, "textCase": 2},
                auth=self._auth,
                timeout=5,
            )
        else:
            # An empty body removes the custom app, returning the
            # display to its normal (clock) face.
            response = requests.post(
                self._url,
                params={"name": self.config.app_name},
                data=b"",
                auth=self._auth,
                timeout=5,
            )
        response.raise_for_status()

        self._last_text = text
