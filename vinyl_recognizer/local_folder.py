"""Local-folder fallback recognizer.

Used when a remote provider is rate-limited (currently: ACRCloud - see
service.py and acrcloud.RateLimitedError) and you'd rather get a match
from your own collection than nothing at all. Matches the current clip
against a folder of your own reference clips by comparing Chromaprint
fingerprints (via `fpcalc`) - everything happens on this machine, no
network calls.

Each reference file's name (minus extension) is the recognition result,
in "Artist - Title - Album" form (album is optional), e.g.
"Pink Floyd - Comfortably Numb - The Wall.flac". Only records you've
placed a reference clip for can be matched this way.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Minimum fraction of matching fingerprint bits (0-1) for a reference
# clip to count as a match. Chromaprint fingerprints of the same
# recording typically agree well above this; unrelated audio sits close
# to 0.5 (random chance for a bitwise comparison).
_MATCH_THRESHOLD = 0.85


def recognize(wav_bytes: bytes, folder: str) -> Optional[dict]:
    """Identify a clip by comparing it against every reference clip in
    `folder`.

    Returns a dict with `title`, `artist`, `album` parsed from the best
    matching file's name (`artwork_url` is always "" - there's no cover
    art lookup here), or None if no reference clip is similar enough, the
    folder is empty/missing, or `fpcalc` is unavailable.
    """
    if shutil.which("fpcalc") is None:
        logger.error("fpcalc not found on PATH - install the Chromaprint command-line tools")
        return None

    reference_dir = Path(folder)
    if not reference_dir.is_dir():
        logger.error("Local-folder fallback directory does not exist: %s", folder)
        return None

    clip_fingerprint = _fingerprint_bytes(wav_bytes)
    if clip_fingerprint is None:
        return None

    best_score = 0.0
    best_path: Optional[Path] = None
    for path in sorted(reference_dir.iterdir()):
        if not path.is_file():
            continue
        reference_fingerprint = _fingerprint_file(path)
        if reference_fingerprint is None:
            continue
        score = _similarity(clip_fingerprint, reference_fingerprint)
        if score > best_score:
            best_score, best_path = score, path

    if best_path is None or best_score < _MATCH_THRESHOLD:
        return None

    logger.info("Local-folder match: %s (score %.2f)", best_path.name, best_score)
    return _parse_filename(best_path)


def _parse_filename(path: Path) -> dict:
    parts = [p.strip() for p in path.stem.split(" - ")]
    return {
        "title": parts[1] if len(parts) > 1 else (parts[0] if parts else ""),
        "artist": parts[0] if len(parts) > 1 else "",
        "album": parts[2] if len(parts) > 2 else "",
        "artwork_url": "",
    }


def _fingerprint_bytes(wav_bytes: bytes) -> Optional[List[int]]:
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(wav_bytes)
        f.flush()
        return _fingerprint_file(Path(f.name))


def _fingerprint_file(path: Path) -> Optional[List[int]]:
    try:
        completed = subprocess.run(
            ["fpcalc", "-raw", "-json", str(path)],
            capture_output=True, timeout=30, check=True,
        )
        result = json.loads(completed.stdout)
        fingerprint = result["fingerprint"]
    except Exception:
        logger.exception("fpcalc failed for %s", path)
        return None

    # `-raw` makes fpcalc emit a comma-separated string of signed int32s
    # instead of the default base64-encoded compressed fingerprint.
    if isinstance(fingerprint, str):
        return [int(x) for x in fingerprint.split(",") if x]
    return list(fingerprint)


def _similarity(a: List[int], b: List[int]) -> float:
    """Best bit-match fraction between two raw Chromaprint fingerprints,
    trying every alignment offset since the two clips were almost
    certainly recorded starting at different points in the track."""
    if not a or not b:
        return 0.0

    best = 0.0
    min_overlap = min(len(a), len(b)) // 4
    for offset in range(-len(b) + 1, len(a)):
        if offset >= 0:
            pairs = list(zip(a[offset:], b))
        else:
            pairs = list(zip(a, b[-offset:]))
        if len(pairs) < min_overlap:
            continue

        matching_bits = sum(32 - bin((x ^ y) & 0xFFFFFFFF).count("1") for x, y in pairs)
        score = matching_bits / (32 * len(pairs))
        if score > best:
            best = score
    return best
