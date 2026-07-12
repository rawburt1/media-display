"""Client for `vibra` (https://github.com/BayernMuller/vibra), a native
CLI tool that talks to Shazam's recognition backend directly - the same
endpoint Shazam's own app uses - without needing Python audio-decoding
dependencies (no ffmpeg, no asyncio). No API key required. Its JSON
output is shaped exactly like shazamio's response, so parsing is shared
with shazam.py via shazam_format.py.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from typing import Optional

from vinyl_recognizer.shazam_format import parse_track

logger = logging.getLogger(__name__)


def recognize(wav_bytes: bytes) -> Optional[dict]:
    """Identify a short audio clip via vibra.

    Requires the `vibra` binary to be installed and on PATH (it isn't
    packaged for apt - build it from source, see the project's README).

    Returns a dict with `title`, `artist`, `album`, `artwork_url` (any of
    which may be empty strings), or None if nothing was recognized, vibra
    is unavailable, or the request failed.
    """
    if shutil.which("vibra") is None:
        logger.error("vibra not found on PATH - see https://github.com/BayernMuller/vibra")
        return None

    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(wav_bytes)
        f.flush()
        try:
            completed = subprocess.run(
                ["vibra", "--recognize", "--file", f.name],
                capture_output=True,
                timeout=30,
                check=True,
            )
        except Exception:
            logger.exception("vibra failed")
            return None

    try:
        data = json.loads(completed.stdout)
    except Exception:
        logger.exception("Could not parse vibra output")
        return None

    return parse_track(data)
