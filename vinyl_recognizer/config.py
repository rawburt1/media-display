"""Configuration loading: YAML file -> RecognizerConfig."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Union

import yaml


@dataclasses.dataclass
class RecognizerConfig:
    # Which recognition API to use: "audd", "acrcloud", "acoustid",
    # "shazam", or "vibra" (shazam and vibra need no API key - see
    # shazam.py / vibra.py).
    recognition_provider: str = "audd"

    # API token from https://dashboard.audd.io/
    audd_api_key: str = ""

    # ACRCloud project credentials from the console's "Audio & Video
    # Recognition" project page. `acrcloud_host` is the project's
    # identification endpoint, e.g. "identify-eu-west-1.acrcloud.com".
    acrcloud_host: str = ""
    acrcloud_access_key: str = ""
    acrcloud_access_secret: str = ""

    # Folder of your own reference clips (see local_folder.py) to match
    # against, temporarily, whenever ACRCloud reports it's rate-limiting
    # us - empty (the default) disables this and just treats a rate
    # limit as a plain miss. Only used when recognition_provider is
    # "acrcloud".
    local_folder_fallback_dir: str = ""

    # API key from https://acoustid.org/my-applications. Requires the
    # `fpcalc` binary (Chromaprint) to be installed - see acoustid.py.
    acoustid_api_key: str = ""

    # Input device name (substring match) or index, as shown by
    # `python -m vinyl_recognizer --list-devices`. Empty uses the system
    # default input device.
    input_device: str = ""

    sample_rate: int = 44100

    # How often (in seconds) to record a short clip to check for signal.
    poll_interval_seconds: float = 5.0

    # Length (in seconds) of the short clip used for signal detection.
    signal_clip_seconds: float = 1.0

    # Length (in seconds) of the clip sent to AudD for recognition.
    recognition_clip_seconds: float = 8.0

    # Minimum time (in seconds) between AudD recognition requests while
    # audio keeps playing.
    recognition_interval_seconds: float = 60.0

    # RMS amplitude (0-1) below which audio is considered silence.
    silence_threshold: float = 0.01

    # How long (in seconds) signal must be absent before the current
    # recognition result is cleared (i.e. "nothing playing").
    silence_grace_seconds: float = 15.0

    # HTTP server bind address/port for the /now-playing endpoint.
    host: str = "0.0.0.0"
    port: int = 8091

    @classmethod
    def load(cls, path: Union[str, Path]) -> "RecognizerConfig":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found: {path}. "
                "Copy config.example.yaml to config.yaml and fill in your settings."
            )

        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        return cls(**raw)
