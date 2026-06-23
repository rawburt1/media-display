"""Parses Shazam-schema track JSON, shared by the two clients that talk
to Shazam's backend and get this exact response shape back: shazam.py
(via the shazamio library) and vibra.py (via the vibra native binary).
"""

from __future__ import annotations

from typing import Optional


def parse_track(data: dict) -> Optional[dict]:
    """Turn a raw Shazam-schema response into our common recognition dict.

    Returns a dict with `title`, `artist`, `album`, `artwork_url` (any of
    which may be empty strings), or None if no track was matched.
    """
    track = (data or {}).get("track")
    if not track:
        return None

    return {
        "title": track.get("title") or "",
        "artist": track.get("subtitle") or "",
        "album": _album(track),
        "artwork_url": _best_artwork(track),
    }


def _album(track: dict) -> str:
    for section in track.get("sections") or []:
        for meta in section.get("metadata") or []:
            if meta.get("title") == "Album":
                return meta.get("text") or ""
    return ""


def _best_artwork(track: dict) -> str:
    images = track.get("images") or {}
    return images.get("coverarthq") or images.get("coverart") or ""
