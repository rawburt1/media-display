"""Tests for audio capture helpers."""

import wave
from io import BytesIO

import numpy as np

from vinyl_recognizer import recorder


def test_resolve_device_empty_is_default():
    assert recorder.resolve_device("") is None


def test_resolve_device_numeric_string_is_index():
    assert recorder.resolve_device("3") == 3


def test_resolve_device_name_passthrough():
    assert recorder.resolve_device("UCA202") == "UCA202"


def test_rms_of_silence_is_zero():
    silence = np.zeros(1000, dtype=np.int16)
    assert recorder.rms(silence) == 0.0


def test_rms_of_full_scale_is_one():
    full_scale = np.full(1000, 32767, dtype=np.int16)
    assert recorder.rms(full_scale) > 0.99


def test_rms_of_empty_array_is_zero():
    assert recorder.rms(np.array([], dtype=np.int16)) == 0.0


def test_to_wav_bytes_round_trips():
    audio = np.array([0, 100, -100, 32767, -32768], dtype=np.int16)

    wav_bytes = recorder.to_wav_bytes(audio, sample_rate=44100)

    with wave.open(BytesIO(wav_bytes), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 44100
        frames = wf.readframes(wf.getnframes())

    decoded = np.frombuffer(frames, dtype=np.int16)
    assert np.array_equal(decoded, audio)
