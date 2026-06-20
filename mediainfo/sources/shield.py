"""Android TV "now playing" source (e.g. Nvidia Shield), via ADB.

Reports the currently-playing media session from *any* app (Spotify,
YouTube Music, SVT Play, etc.) by polling `dumpsys media_session` over ADB.
No artwork is available directly this way, so this relies on:
- the fanart.tv enricher's MusicBrainz artist/album lookup, for apps that
  report an album name (see enrichers/fanarttv.py).
- the thetvdb.com enricher's title-based series search, for apps known to
  stream TV/video rather than music (see _VIDEO_PACKAGES below and
  enrichers/thetvdb.py) - these get reported as "episode" instead of
  "music" so that enricher actually runs.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Tuple

from adb_shell.adb_device import AdbDeviceTcp
from adb_shell.auth.keygen import keygen
from adb_shell.auth.sign_pythonrsa import PythonRSASigner

from mediainfo.config import ShieldConfig
from mediainfo.models import NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# PlaybackState.STATE_PLAYING
_STATE_PLAYING = 3

_ACTIVE_RE = re.compile(r"^active=(true|false)")
_STATE_RE = re.compile(r"^state=PlaybackState \{state=(\d+)")
_DESCRIPTION_RE = re.compile(r"^metadata: size=\d+, description=(.*)$")
_PACKAGE_RE = re.compile(r"^package=(.+)$")
_SESSION_HEADER_RE = re.compile(r"\(userId=\d+\)\s*$")

# Apps known to stream TV/video content rather than music. Their session
# reports the same generic "title, subtitle, album" shape as a music app
# (dumpsys gives no reliable way to tell them apart), so without this we'd
# never know to treat e.g. "Kingdom, 5. När makten skiftar" as a TV show
# rather than a song - and the thetvdb enricher only runs for
# media_type == "episode". Add to this set as you find more.
_VIDEO_PACKAGES = {
    "se.svt.android.svtplay",  # SVT Play (Swedish public broadcaster)
}


class ShieldSource(MediaSource):
    name = "shield"

    def __init__(self, config: ShieldConfig):
        self.config = config
        self._signer = self._load_or_create_signer(Path(config.adb_key_path))
        self._device = AdbDeviceTcp(
            config.host, config.port, default_transport_timeout_s=9.0
        )

    @staticmethod
    def _load_or_create_signer(key_path: Path) -> PythonRSASigner:
        if not key_path.exists():
            key_path.parent.mkdir(parents=True, exist_ok=True)
            keygen(str(key_path))
            logger.info(
                "Generated new ADB key at %s - accept the authorization "
                "prompt on the device's screen",
                key_path,
            )
        return PythonRSASigner.FromRSAKeyPath(str(key_path))

    def get_now_playing(self) -> Optional[NowPlaying]:
        self.last_poll_failed = False
        try:
            dump = self._shell("dumpsys media_session")
        except Exception:
            logger.exception("Shield source error")
            self.last_poll_failed = True
            return None

        session = self._find_playing_session(dump)
        if session is None:
            return None
        description, package = session

        title, subtitle, album = self._parse_description(description)
        if not title:
            return None

        media_type = "episode" if package in _VIDEO_PACKAGES else "music"

        return NowPlaying(
            source=self.name,
            media_type=media_type,
            title=title,
            subtitle=subtitle,
            album=album,
        )

    def _shell(self, command: str) -> str:
        if not self._device.available:
            self._device.connect(rsa_keys=[self._signer], auth_timeout_s=10.0)
        try:
            return self._device.shell(command)
        except Exception:
            self._device.close()
            raise

    @staticmethod
    def _find_playing_session(dump: str) -> Optional[Tuple[str, str]]:
        """Return (description, package) for the first active, playing
        session in the "Sessions Stack" section - package is the app's
        package name (e.g. "se.svt.android.svtplay"), used to tell video
        apps apart from music ones (see _VIDEO_PACKAGES above).
        """
        in_stack = False
        header_indent: Optional[int] = None
        active = False
        state: Optional[int] = None
        description: Optional[str] = None
        package: str = ""

        def is_match() -> bool:
            return active and state == _STATE_PLAYING and description is not None

        for line in dump.splitlines():
            if "Sessions Stack" in line:
                in_stack = True
                continue
            if not in_stack:
                continue

            stripped = line.strip()
            if not stripped:
                continue
            indent = len(line) - len(line.lstrip())
            if header_indent is None:
                header_indent = indent

            if indent <= header_indent:
                if is_match() and description is not None:
                    return description, package
                if not _SESSION_HEADER_RE.search(stripped):
                    break  # end of the "Sessions Stack" section
                active, state, description, package = False, None, None, ""
                continue

            match = _ACTIVE_RE.match(stripped)
            if match:
                active = match.group(1) == "true"
                continue

            match = _STATE_RE.match(stripped)
            if match:
                state = int(match.group(1))
                continue

            match = _DESCRIPTION_RE.match(stripped)
            if match:
                description = match.group(1)
                continue

            match = _PACKAGE_RE.match(stripped)
            if match:
                package = match.group(1)
                continue

        return (description, package) if is_match() and description is not None else None

    @staticmethod
    def _parse_description(description: str) -> Tuple[str, str, str]:
        parts = [p.strip() for p in description.split(",", 2)]
        parts += [""] * (3 - len(parts))
        a, b, c = ("" if p == "null" else p for p in parts[:3])
        return a, b, c
