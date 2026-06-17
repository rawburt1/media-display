"""Tests for the background recognition loop."""

from unittest.mock import patch

import numpy as np

from vinyl_recognizer.config import RecognizerConfig
from vinyl_recognizer.service import RecognizerService

_LOUD = np.full(10, 32767, dtype=np.int16)
_SILENT = np.zeros(10, dtype=np.int16)


def _service(**overrides) -> RecognizerService:
    config = RecognizerConfig(
        audd_api_key="test-key",
        recognition_interval_seconds=60,
        silence_grace_seconds=15,
        silence_threshold=0.01,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return RecognizerService(config)


@patch("vinyl_recognizer.service.audd.recognize")
@patch("vinyl_recognizer.service.recorder.record_clip")
def test_silence_does_not_call_audd(mock_record, mock_recognize):
    mock_record.return_value = _SILENT
    service = _service()

    service.tick()

    mock_recognize.assert_not_called()
    assert service.get_now_playing() == {}


@patch("vinyl_recognizer.service.audd.recognize")
@patch("vinyl_recognizer.service.recorder.record_clip")
def test_signal_triggers_recognition(mock_record, mock_recognize):
    mock_record.return_value = _LOUD
    mock_recognize.return_value = {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "https://example.com/cover.jpg",
    }
    service = _service()

    service.tick()

    mock_recognize.assert_called_once()
    assert service.get_now_playing()["title"] == "Comfortably Numb"


@patch("vinyl_recognizer.service.audd.recognize")
@patch("vinyl_recognizer.service.recorder.record_clip")
def test_recognition_not_repeated_before_interval_elapses(mock_record, mock_recognize):
    mock_record.return_value = _LOUD
    mock_recognize.return_value = {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "",
    }
    service = _service()

    service.tick()
    service.tick()

    mock_recognize.assert_called_once()


@patch("vinyl_recognizer.service.audd.recognize")
@patch("vinyl_recognizer.service.recorder.record_clip")
def test_no_match_leaves_current_unset(mock_record, mock_recognize):
    mock_record.return_value = _LOUD
    mock_recognize.return_value = None
    service = _service()

    service.tick()

    assert service.get_now_playing() == {}


@patch("vinyl_recognizer.service.audd.recognize")
@patch("vinyl_recognizer.service.recorder.record_clip")
@patch("vinyl_recognizer.service.time.monotonic")
def test_silence_after_grace_period_clears_current_track(mock_monotonic, mock_record, mock_recognize):
    mock_recognize.return_value = {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "",
    }
    service = _service()

    # First tick: loud, recognized. (A non-zero start time avoids colliding
    # with the "never" sentinel used for _last_signal/_last_recognition.)
    mock_monotonic.return_value = 100.0
    mock_record.return_value = _LOUD
    service.tick()
    assert service.get_now_playing()["title"] == "Comfortably Numb"

    # Second tick: silence, but within the grace period.
    mock_monotonic.return_value = 105.0
    mock_record.return_value = _SILENT
    service.tick()
    assert service.get_now_playing()["title"] == "Comfortably Numb"

    # Third tick: silence past the grace period - track is cleared.
    mock_monotonic.return_value = 120.0
    service.tick()
    assert service.get_now_playing() == {}
