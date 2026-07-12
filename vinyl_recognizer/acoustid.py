"""Client for the AcoustID audio recognition API (https://acoustid.org/).

Unlike AudD/ACRCloud, AcoustID doesn't accept raw audio - it matches
against a Chromaprint *fingerprint*, computed here by shelling out to the
`fpcalc` command-line tool (from the Chromaprint project). No raw audio is
ever sent anywhere for this provider.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_LOOKUP_URL = "https://api.acoustid.org/v2/lookup"


def recognize(wav_bytes: bytes, api_key: str) -> Optional[dict]:
    """Identify a short audio clip via AcoustID.

    Requires the `fpcalc` binary to be installed and on PATH.

    Returns a dict with `title`, `artist`, `album` (`artwork_url` is
    always "" - AcoustID has no cover art of its own), or None if nothing
    was recognized, fpcalc is unavailable, or the request failed.
    """
    fingerprint = _fingerprint(wav_bytes)
    if fingerprint is None:
        return None
    duration, fp = fingerprint

    try:
        response = requests.post(
            _LOOKUP_URL,
            data={
                "client": api_key,
                "duration": str(duration),
                "fingerprint": fp,
                "meta": "recordings+releasegroups",
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        logger.exception("AcoustID request failed")
        return None

    if data.get("status") != "ok":
        logger.warning("AcoustID error response: %r", data)
        return None

    results = data.get("results") or []
    if not results:
        return None

    best = max(results, key=lambda r: r.get("score", 0))
    recordings = best.get("recordings") or []
    if not recordings:
        return None
    recording = recordings[0]

    artists = recording.get("artists") or []
    releasegroups = recording.get("releasegroups") or []

    return {
        "title": recording.get("title") or "",
        "artist": artists[0].get("name", "") if artists else "",
        "album": releasegroups[0].get("title", "") if releasegroups else "",
        "artwork_url": "",
    }


def _fingerprint(wav_bytes: bytes) -> Optional[tuple]:
    """Run `fpcalc -json` on the clip and return (duration_seconds, fingerprint),
    or None if fpcalc is missing or fails."""
    if shutil.which("fpcalc") is None:
        logger.error("fpcalc not found on PATH - install the Chromaprint command-line tools")
        return None

    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(wav_bytes)
        f.flush()
        try:
            completed = subprocess.run(
                ["fpcalc", "-json", f.name],
                capture_output=True,
                timeout=30,
                check=True,
            )
        except Exception:
            logger.exception("fpcalc failed")
            return None

    try:
        result = json.loads(completed.stdout)
        return int(result["duration"]), result["fingerprint"]
    except Exception:
        logger.exception("Could not parse fpcalc output")
        return None
