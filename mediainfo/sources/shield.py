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

from typing import Optional, Tuple

from mediainfo.models import NowPlaying
from mediainfo.sources.adb_base import (
    ACTIVE_RE,
    DESCRIPTION_RE,
    PACKAGE_RE,
    SESSION_HEADER_RE,
    STATE_PLAYING,
    STATE_RE,
    AdbNowPlayingSource,
)

# Apps known to stream TV/video content rather than music. Their session
# reports the same generic "title, subtitle, album" shape as a music app
# (dumpsys gives no reliable way to tell them apart), so without this we'd
# never know to treat e.g. "Kingdom, 5. När makten skiftar" as a TV show
# rather than a song - and the thetvdb enricher only runs for
# media_type == "episode". Add to this set as you find more.
_VIDEO_PACKAGES = {
    "se.svt.android.svtplay",  # SVT Play (Swedish public broadcaster)
}


class ShieldSource(AdbNowPlayingSource):
    name = "shield"

    def _parse_dump(self, dump: str) -> Optional[NowPlaying]:
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
            return active and state == STATE_PLAYING and description is not None

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
                if not SESSION_HEADER_RE.search(stripped):
                    break  # end of the "Sessions Stack" section
                active, state, description, package = False, None, None, ""
                continue

            match = ACTIVE_RE.match(stripped)
            if match:
                active = match.group(1) == "true"
                continue

            match = STATE_RE.match(stripped)
            if match:
                state = int(match.group(1))
                continue

            match = DESCRIPTION_RE.match(stripped)
            if match:
                description = match.group(1)
                continue

            match = PACKAGE_RE.match(stripped)
            if match:
                package = match.group(1)
                continue

        return (description, package) if is_match() and description is not None else None
