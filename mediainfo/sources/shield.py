"""Android TV "now playing" source (e.g. Nvidia Shield), via ADB.

Reports the currently-playing media session from *any* app (Spotify,
YouTube Music, SVT Play, etc.) by polling `dumpsys media_session` over ADB.
No artwork is available this way, so this relies on the fanart.tv
enricher's MusicBrainz artist/album lookup for apps that report an album
name (see enrichers/fanarttv.py).
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
_SESSION_HEADER_RE = re.compile(r"\(userId=\d+\)\s*$")


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

        description = self._find_playing_description(dump)
        if description is None:
            return None

        title, subtitle, album = self._parse_description(description)
        if not title:
            return None

        return NowPlaying(
            source=self.name,
            media_type="music",
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
    def _find_playing_description(dump: str) -> Optional[str]:
        """Return the `metadata: ... description=...` value of the first
        active, playing session in the "Sessions Stack" section.
        """
        in_stack = False
        header_indent: Optional[int] = None
        active = False
        state: Optional[int] = None
        description: Optional[str] = None

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
                if is_match():
                    return description
                if not _SESSION_HEADER_RE.search(stripped):
                    break  # end of the "Sessions Stack" section
                active, state, description = False, None, None
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

        return description if is_match() else None

    @staticmethod
    def _parse_description(description: str) -> Tuple[str, str, str]:
        parts = [p.strip() for p in description.split(",", 2)]
        parts += [""] * (3 - len(parts))
        return tuple("" if p == "null" else p for p in parts[:3])
