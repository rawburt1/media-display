"""YouTube (Android TV app) "now playing" source, via ADB.

Targets the YouTube app specifically (package com.google.android.youtube.tv
on Android TV devices, e.g. Nvidia Shield), unlike the generic `shield`
source which reports whatever app currently has an active media session.

YouTube's regular video app doesn't reliably report a separate artist field
via its media session, so this only reports "now playing" when the content
looks like a song, using two heuristics (checked in order):

1. The channel name follows YouTube's well-known auto-generated convention
   for officially distributed music: "<Artist> - Topic". This is the most
   reliable signal and gives a clean artist name directly.
2. The video title itself follows the common "<Artist> - <Song>" convention
   used by official audio/lyric videos, with trailing decorations like
   "(Official Video)" stripped.

Anything else (a vlog, a tutorial, a movie trailer, etc.) is treated as "not
a song" and ignored - get_now_playing() returns None, so other sources or
the idle wallpaper take over. Once an artist name is identified, normal
music enrichment (fanart.tv/MusicBrainz/Last.fm/Discogs/Wikipedia) takes
over to fetch artwork and bio info from whichever of those is configured,
exactly as for any other music source.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Tuple

from adb_shell.adb_device import AdbDeviceTcp
from adb_shell.auth.keygen import keygen
from adb_shell.auth.sign_pythonrsa import PythonRSASigner

from mediainfo.config import YoutubeConfig
from mediainfo.models import NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# PlaybackState.STATE_PLAYING
_STATE_PLAYING = 3

# Package name of the YouTube app on Android TV (e.g. Nvidia Shield).
_PACKAGE = "com.google.android.youtube.tv"

_PACKAGE_RE = re.compile(r"^package=(.+)$")
_ACTIVE_RE = re.compile(r"^active=(true|false)")
_STATE_RE = re.compile(r"^state=PlaybackState \{state=(\d+)")
_DESCRIPTION_RE = re.compile(r"^metadata: size=\d+, description=(.*)$")
_SESSION_HEADER_RE = re.compile(r"\(userId=\d+\)\s*$")

# YouTube's auto-generated channel name for officially distributed music
# (e.g. "Queen - Topic").
_TOPIC_CHANNEL_RE = re.compile(r"^(.+?)\s+-\s+Topic$")
# "<Artist> - <Song>" convention used by official audio/lyric videos.
_ARTIST_TITLE_RE = re.compile(r"^(.+?)\s+-\s+(.+)$")
# Trailing decorations commonly appended to official music video titles,
# e.g. "(Official Video)", "[Official Audio]", "(Lyrics)".
_DECORATION_RE = re.compile(
    r"\s*[\(\[]\s*(official\s+)?(music\s+)?(video|audio|lyrics?|visualizer)\s*[\)\]]\s*$",
    re.IGNORECASE,
)


class YoutubeSource(MediaSource):
    name = "youtube"

    def __init__(self, config: YoutubeConfig):
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
        try:
            dump = self._shell("dumpsys media_session")
        except Exception:
            logger.exception("YouTube source error")
            return None

        description = self._find_youtube_description(dump)
        if description is None:
            return None

        video_title, channel, _ = self._parse_description(description)
        if not video_title:
            return None

        artist, song_title = self._detect_song(video_title, channel)
        if artist is None:
            return None

        return NowPlaying(
            source=self.name,
            media_type="music",
            title=song_title,
            subtitle=artist,
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
    def _find_youtube_description(dump: str) -> Optional[str]:
        """Return the `metadata: ... description=...` value of the YouTube
        app's session, if it is active and playing.
        """
        in_stack = False
        header_indent: Optional[int] = None
        package: Optional[str] = None
        active = False
        state: Optional[int] = None
        description: Optional[str] = None

        def is_match() -> bool:
            return (
                package == _PACKAGE
                and active
                and state == _STATE_PLAYING
                and description is not None
            )

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
                package, active, state, description = None, False, None, None
                continue

            match = _PACKAGE_RE.match(stripped)
            if match:
                package = match.group(1)
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

    @classmethod
    def _detect_song(
        cls, video_title: str, channel: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Return (artist, song_title), or (None, None) if this doesn't
        look like a song being played, rather than some other video.
        """
        match = _TOPIC_CHANNEL_RE.match(channel)
        if match:
            return match.group(1).strip(), cls._strip_decoration(video_title)

        match = _ARTIST_TITLE_RE.match(video_title)
        if match:
            artist = match.group(1).strip()
            song = cls._strip_decoration(match.group(2))
            if artist and song:
                return artist, song

        return None, None

    @staticmethod
    def _strip_decoration(title: str) -> str:
        return _DECORATION_RE.sub("", title).strip()
