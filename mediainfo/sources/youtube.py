"""YouTube (Android TV app) "now playing" source, via ADB.

Targets the YouTube app specifically (package com.google.android.youtube.tv
on Android TV devices, e.g. Nvidia Shield), unlike the generic `shield`
source which reports whatever app currently has an active media session.

YouTube's Android TV app doesn't expose a field that reliably distinguishes
a song from any other video - a music track's media session looks exactly
like a vlog's: `description=<title>, <channel>, null`. There's no "this is
music" flag and no separate clean artist field to filter on (an early
version of this source tried to detect a "<Artist> - Topic" channel suffix
or an "<Artist> - <Song>" title pattern, but real-world testing showed
YouTube TV reports the channel as just "Phil Collins", not
"Phil Collins - Topic" - so neither heuristic actually fired). So this
reports whatever's actively playing in YouTube as music, with the channel
name as `subtitle` (treated as the artist) by default.

Some videos instead encode the artist in the title itself, as
"<Song> - <Artist>" (song first, then artist - the reverse of the usual
"Artist - Song" convention seen elsewhere). When the title matches that
shape, it's split and the title's artist wins over the channel name -
unless the part after the dash is a version/edition tag like "Live" or
"Remix" rather than an artist (see `_QUALIFIER_WORDS`), in which case it's
just decoration and the channel name is used as the artist as usual.

All parenthesized/bracketed content (e.g. "(Official Video)", "[Remastered
2011]") is stripped from the title, plus any trailing " - <tag>" segment
naming a version/edition (see `_QUALIFIER_WORDS`). A dash glued directly
onto a word with no space before it (e.g. "Led Zeppelin- The Battle of
Evermore") is treated as a stray punctuation artifact and removed outright
rather than as a "<Song> - <Artist>" separator.

Music enrichment (fanart.tv/MusicBrainz/Last.fm/Discogs/Wikipedia) then
takes over to fetch artwork and bio info from whichever of those is
configured, exactly as for any other music source; if the "artist" name
doesn't correspond to a real one (e.g. for a non-music video), those
enrichers will simply find nothing to add.
"""

from __future__ import annotations

import re
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

# Package name of the YouTube app on Android TV (e.g. Nvidia Shield).
_PACKAGE = "com.google.android.youtube.tv"

# Any parenthesized/bracketed content, e.g. "(Official Video)",
# "[Remastered 2011]", "(feat. Someone)" - removed from the title entirely.
_PAREN_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]\s*")

# A dash glued directly onto the end of a word with no space before it
# (e.g. "Led Zeppelin- The Battle of Evermore") is a stray punctuation
# artifact in the original title, not a "<Song> - <Artist>" separator -
# removed outright. Properly-spaced dashes (with a space on both sides)
# are left alone, since those are what _detect_song_artist looks for.
_STRAY_DASH_RE = re.compile(r"(?<=\S)-(?=\s)")

# Version/edition tags that indicate a trailing "- <word>" segment is *not*
# an artist name (e.g. "Song - Live", "Song - Remix").
_QUALIFIER_WORDS = (
    "remix",
    "live",
    "acoustic",
    "cover",
    "demo",
    "instrumental",
    "extended",
    "edit",
    "version",
    "mix",
    "remaster",
    "remastered",
    "mono",
    "stereo",
    "karaoke",
    "tribute",
    "medley",
    "explicit",
    "clean",
    "unplugged",
    "session",
    "sessions",
    "performance",
)
_QUALIFIER_RE = re.compile(r"\b(" + "|".join(_QUALIFIER_WORDS) + r")\b", re.IGNORECASE)
# A trailing " - <phrase containing a qualifier word>" suffix to strip.
_TRAILING_QUALIFIER_RE = re.compile(
    r"\s*-\s*[^-]*\b(" + "|".join(_QUALIFIER_WORDS) + r")\b[^-]*$",
    re.IGNORECASE,
)


class YoutubeSource(AdbNowPlayingSource):
    name = "youtube"

    def _parse_dump(self, dump: str) -> Optional[NowPlaying]:
        description = self._find_youtube_description(dump)
        if description is None:
            return None

        video_title, channel, _ = self._parse_description(description)
        if not video_title:
            return None

        title, artist = self._detect_song_artist(video_title, channel)

        return NowPlaying(
            source=self.name,
            media_type="music",
            title=title,
            subtitle=artist,
        )

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
                and state == STATE_PLAYING
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
                if not SESSION_HEADER_RE.search(stripped):
                    break  # end of the "Sessions Stack" section
                package, active, state, description = None, False, None, None
                continue

            match = PACKAGE_RE.match(stripped)
            if match:
                package = match.group(1)
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

        return description if is_match() else None

    @classmethod
    def _detect_song_artist(cls, video_title: str, channel: str) -> Tuple[str, str]:
        """Return (title, artist) for a YouTube video.

        If the title looks like "<Song> - <Artist>" (and <Artist> isn't a
        version/edition tag like "Live" or "Remix"), split it - some videos
        encode the artist this way instead of (or in addition to) the
        channel name. Otherwise fall back to the channel name as the
        artist, as usual.
        """
        cleaned = cls._strip_decoration(video_title)
        if " - " in cleaned:
            song, _, rest = cleaned.partition(" - ")
            song, rest = song.strip(), rest.strip()
            if song and rest and not _QUALIFIER_RE.search(rest):
                return song, rest
        return cleaned, channel

    @staticmethod
    def _strip_decoration(title: str) -> str:
        without_stray_dash = _STRAY_DASH_RE.sub("", title)
        without_parens = _PAREN_RE.sub(" ", without_stray_dash)
        without_qualifier = _TRAILING_QUALIFIER_RE.sub("", without_parens)
        return " ".join(without_qualifier.split()).strip()
