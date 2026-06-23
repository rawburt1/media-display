"""Client for Shazam's (unofficial) recognition API, via the `shazamio`
library (https://github.com/shazamio/ShazamIO). No API key required -
shazamio talks to Shazam's own backend the same way the mobile app does.
Needs `ffmpeg` installed for shazamio's own audio decoding.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from typing import Optional

from shazamio import Shazam

from vinyl_recognizer.shazam_format import parse_track

logger = logging.getLogger(__name__)


def recognize(wav_bytes: bytes) -> Optional[dict]:
    """Identify a short audio clip via Shazam.

    Returns a dict with `title`, `artist`, `album`, `artwork_url` (any of
    which may be empty strings), or None if nothing was recognized or the
    request failed.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(wav_bytes)
        f.flush()
        try:
            data = asyncio.run(_recognize_file(f.name))
        except Exception:
            logger.exception("Shazam request failed")
            return None

    return parse_track(data)


async def _recognize_file(path: str) -> dict:
    shazam = Shazam()
    return await shazam.recognize(path)
