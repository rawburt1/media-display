"""Shared ADB plumbing for Android TV "now playing" sources (shield.py,
youtube.py) that poll `dumpsys media_session` over an ADB connection.

Subclasses provide just the session-scanning/parsing logic that's actually
specific to them - which session in the dump counts as "the" one to report,
and how to turn its description into title/subtitle/album - via
`_parse_dump()`. Everything around that (the RSA keypair/signer, the device
connection, the shell-and-reconnect dance, and the description's
comma-separated field splitting) is identical between them and lives here.
"""

from __future__ import annotations

import logging
import re
from abc import abstractmethod
from pathlib import Path
from typing import Optional, Tuple

from adb_shell.adb_device import AdbDeviceTcp
from adb_shell.auth.keygen import keygen
from adb_shell.auth.sign_pythonrsa import PythonRSASigner

from mediainfo.models import NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# PlaybackState.STATE_PLAYING
STATE_PLAYING = 3

ACTIVE_RE = re.compile(r"^active=(true|false)")
STATE_RE = re.compile(r"^state=PlaybackState \{state=(\d+)")
DESCRIPTION_RE = re.compile(r"^metadata: size=\d+, description=(.*)$")
PACKAGE_RE = re.compile(r"^package=(.+)$")
SESSION_HEADER_RE = re.compile(r"\(userId=\d+\)\s*$")


class AdbNowPlayingSource(MediaSource):
    """Base class for `dumpsys media_session`-polling sources."""

    def __init__(self, config):
        self.config = config
        self._signer = self._load_or_create_signer(Path(config.adb_key_path))
        self._device = AdbDeviceTcp(config.host, config.port, default_transport_timeout_s=9.0)

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
            self.log_poll_error(logger, "%s source error", self.name)
            self.last_poll_failed = True
            return None
        return self._parse_dump(dump)

    @abstractmethod
    def _parse_dump(self, dump: str) -> Optional[NowPlaying]:
        """Return the NowPlaying for this dump, or None if nothing playing."""

    def _shell(self, command: str) -> str:
        if not self._device.available:
            self._device.connect(rsa_keys=[self._signer], auth_timeout_s=10.0)
        try:
            return self._device.shell(command)
        except Exception:
            self._device.close()
            raise

    @staticmethod
    def _parse_description(description: str) -> Tuple[str, str, str]:
        parts = [p.strip() for p in description.split(",", 2)]
        parts += [""] * (3 - len(parts))
        a, b, c = ("" if p == "null" else p for p in parts[:3])
        return a, b, c
