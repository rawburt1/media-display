"""Client for the ACRCloud audio recognition API (https://www.acrcloud.com/)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class RateLimitedError(Exception):
    """Raised instead of returning None when ACRCloud reports the request
    was rejected for rate-limiting/quota reasons, so callers can tell that
    apart from a normal "no match" miss and fall back to something else
    (see service.py's use of local_folder.recognize())."""


def recognize(wav_bytes: bytes, host: str, access_key: str, access_secret: str) -> Optional[dict]:
    """Identify a short audio clip via ACRCloud.

    `host` is the project's identification endpoint host, e.g.
    "identify-eu-west-1.acrcloud.com" (shown on the project's console page).

    Returns a dict with `title`, `artist`, `album`, `artwork_url` (any of
    which may be empty strings), or None if nothing was recognized or the
    request failed. Raises RateLimitedError instead of returning None if
    the rejection looks rate-limit/quota related rather than a plain miss.
    """
    timestamp = str(int(time.time()))
    signature = _sign(access_key, access_secret, timestamp)

    try:
        response = requests.post(
            f"https://{host}/v1/identify",
            data={
                "access_key": access_key,
                "data_type": "audio",
                "signature_version": "1",
                "signature": signature,
                "sample_bytes": str(len(wav_bytes)),
                "timestamp": timestamp,
            },
            files={"sample": ("clip.wav", wav_bytes, "audio/wav")},
            timeout=30,
        )
        if response.status_code == 429:
            raise RateLimitedError(f"ACRCloud HTTP 429: {response.text}")
        response.raise_for_status()
        data = response.json()
    except RateLimitedError:
        raise
    except Exception:
        logger.exception("ACRCloud request failed")
        return None

    status = data.get("status") or {}
    code = status.get("code")
    if code != 0:
        # code 1001 is "no result found" - a normal miss, not an error.
        if code == 1001:
            return None
        if "limit" in (status.get("msg") or "").lower():
            raise RateLimitedError(f"ACRCloud error response: {data!r}")
        logger.warning("ACRCloud error response: %r", data)
        return None

    music = ((data.get("metadata") or {}).get("music") or [None])[0]
    if not music:
        return None

    artists = music.get("artists") or []
    return {
        "title": music.get("title") or "",
        "artist": artists[0].get("name", "") if artists else "",
        "album": (music.get("album") or {}).get("name") or "",
        "artwork_url": _best_artwork(music),
    }


def _sign(access_key: str, access_secret: str, timestamp: str) -> str:
    string_to_sign = "\n".join(
        ["POST", "/v1/identify", access_key, "audio", "1", timestamp]
    )
    digest = hmac.new(
        access_secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def _best_artwork(music: dict) -> str:
    external = music.get("external_metadata") or {}

    spotify_images = ((external.get("spotify") or {}).get("album") or {}).get("images") or []
    if spotify_images:
        return spotify_images[0].get("url", "")

    deezer_cover = (external.get("deezer") or {}).get("album") or {}
    for key in ("cover_xl", "cover_big", "cover_medium", "cover"):
        if deezer_cover.get(key):
            return deezer_cover[key]

    return ""
