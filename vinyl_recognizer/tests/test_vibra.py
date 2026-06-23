"""Tests for the vibra (native Shazam) client."""

import json
from unittest.mock import MagicMock, patch

from vinyl_recognizer import vibra


def _vibra_output(track):
    completed = MagicMock()
    completed.stdout = json.dumps({"track": track}).encode()
    return completed


@patch("vinyl_recognizer.vibra.subprocess.run")
@patch("vinyl_recognizer.vibra.shutil.which", return_value="/usr/local/bin/vibra")
def test_recognize_returns_track_with_artwork(mock_which, mock_run):
    mock_run.return_value = _vibra_output(
        {
            "title": "Comfortably Numb",
            "subtitle": "Pink Floyd",
            "images": {"coverart": "https://example.com/cover.jpg"},
            "sections": [{"type": "SONG", "metadata": [{"title": "Album", "text": "The Wall"}]}],
        }
    )

    result = vibra.recognize(b"wav-bytes")

    assert result == {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "https://example.com/cover.jpg",
    }

    args, kwargs = mock_run.call_args
    assert args[0][:3] == ["vibra", "--recognize", "--file"]


@patch("vinyl_recognizer.vibra.shutil.which", return_value=None)
def test_recognize_returns_none_when_vibra_missing(mock_which):
    assert vibra.recognize(b"wav-bytes") is None


@patch("vinyl_recognizer.vibra.subprocess.run")
@patch("vinyl_recognizer.vibra.shutil.which", return_value="/usr/local/bin/vibra")
def test_recognize_returns_none_when_vibra_fails(mock_which, mock_run):
    mock_run.side_effect = RuntimeError("vibra crashed")

    assert vibra.recognize(b"wav-bytes") is None


@patch("vinyl_recognizer.vibra.subprocess.run")
@patch("vinyl_recognizer.vibra.shutil.which", return_value="/usr/local/bin/vibra")
def test_recognize_returns_none_on_unparseable_output(mock_which, mock_run):
    completed = MagicMock()
    completed.stdout = b"not json"
    mock_run.return_value = completed

    assert vibra.recognize(b"wav-bytes") is None


@patch("vinyl_recognizer.vibra.subprocess.run")
@patch("vinyl_recognizer.vibra.shutil.which", return_value="/usr/local/bin/vibra")
def test_recognize_returns_none_when_no_track(mock_which, mock_run):
    completed = MagicMock()
    completed.stdout = json.dumps({"matches": []}).encode()
    mock_run.return_value = completed

    assert vibra.recognize(b"wav-bytes") is None
