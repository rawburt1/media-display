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


def test_importing_recorder_does_not_initialize_audio():
    """sounddevice initializes PortAudio on import and raises without an
    audio server (as on CI runners) - the recorder module must load anyway."""
    import subprocess
    import sys

    code = (
        "import sys\n"
        "class _Boom:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'sounddevice':\n"
        "            raise OSError('Error initializing PortAudio')\n"
        "sys.meta_path.insert(0, _Boom())\n"
        "import vinyl_recognizer.recorder, vinyl_recognizer.service, vinyl_recognizer.server\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_record_clip_uses_sounddevice(monkeypatch):
    from unittest.mock import MagicMock

    fake = MagicMock()
    fake.rec.return_value = np.zeros((4, 1), dtype=np.int16)
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", fake)
    clip = recorder.record_clip(0.1, sample_rate=40, device=None)
    fake.rec.assert_called_once_with(4, samplerate=40, channels=1, dtype="int16", device=None)
    fake.wait.assert_called_once()
    assert clip.shape == (4,)
