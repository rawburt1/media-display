"""Client for the AudD audio recognition API (https://audd.io/)."""

from __future__ import annotations

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_AUDD_URL = "https://api.audd.io/"


def recognize(wav_bytes: bytes, api_key: str) -> Optional[dict]:
    """Identify a short audio clip via AudD.

    Returns a dict with `title`, `artist`, `album`, `artwork_url` (any of
    which may be empty strings), or None if nothing was recognized or the
    request failed.
    """
    try:
        response = requests.post(
            _AUDD_URL,
            data={"api_token": api_key, "return": "apple_music,spotify"},
            files={"file": ("clip.wav", wav_bytes, "audio/wav")},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        logger.exception("AudD request failed")
        return None

    if data.get("status") != "success":
        logger.warning("AudD error response: %r", data)
        return None

    result = data.get("result")
    if not result:
        return None

    return {
        "title": result.get("title") or "",
        "artist": result.get("artist") or "",
        "album": result.get("album") or "",
        "artwork_url": _best_artwork(result),
    }


def _best_artwork(result: dict) -> str:
    apple = (result.get("apple_music") or {}).get("artwork") or {}
    url = apple.get("url")
    if url:
        return url.replace("{w}", "600").replace("{h}", "600")

    spotify_images = ((result.get("spotify") or {}).get("album") or {}).get("images") or []
    if spotify_images:
        return spotify_images[0].get("url", "")

    return ""
