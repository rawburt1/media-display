"""Audio capture helpers built on sounddevice."""

from __future__ import annotations

import io
import wave
from typing import Union

import numpy as np
import sounddevice as sd


def resolve_device(input_device: str) -> Union[int, str, None]:
    """Turn a config string into something sounddevice's `device=` accepts.

    Numeric strings are treated as device indices; anything else is passed
    through as a name (sounddevice matches by substring). An empty string
    means "use the default input device".
    """
    if not input_device:
        return None
    if input_device.isdigit():
        return int(input_device)
    return input_device


def record_clip(duration_seconds: float, sample_rate: int, device: Union[int, str, None]) -> np.ndarray:
    """Record a mono 16-bit clip and return it as a 1-D numpy array."""
    frames = int(duration_seconds * sample_rate)
    audio = sd.rec(frames, samplerate=sample_rate, channels=1, dtype="int16", device=device)
    sd.wait()
    return audio.reshape(-1)


def rms(audio: np.ndarray) -> float:
    """Root-mean-square amplitude, normalized to 0-1."""
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)) / 32768.0)


def to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """Encode a mono 16-bit numpy array as WAV file bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()
