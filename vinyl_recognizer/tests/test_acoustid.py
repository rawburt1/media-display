"""Tests for the AcoustID API client."""

import json
from unittest.mock import MagicMock, patch

from vinyl_recognizer import acoustid


def _fpcalc_output(duration=180, fingerprint="AQAB..."):
    completed = MagicMock()
    completed.stdout = json.dumps({"duration": duration, "fingerprint": fingerprint}).encode()
    return completed


@patch("vinyl_recognizer.acoustid.requests.post")
@patch("vinyl_recognizer.acoustid.subprocess.run")
@patch("vinyl_recognizer.acoustid.shutil.which", return_value="/usr/bin/fpcalc")
def test_recognize_returns_track_from_best_scoring_result(mock_which, mock_run, mock_post):
    mock_run.return_value = _fpcalc_output()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "status": "ok",
        "results": [
            {
                "score": 0.5,
                "recordings": [{"title": "Wrong Track", "artists": [{"name": "Nobody"}]}],
            },
            {
                "score": 0.95,
                "recordings": [
                    {
                        "title": "Comfortably Numb",
                        "artists": [{"name": "Pink Floyd"}],
                        "releasegroups": [{"title": "The Wall"}],
                    }
                ],
            },
        ],
    }
    mock_post.return_value = mock_response

    result = acoustid.recognize(b"wav-bytes", "test-key")

    assert result == {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "",
    }

    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.acoustid.org/v2/lookup"
    assert kwargs["data"]["client"] == "test-key"
    assert kwargs["data"]["fingerprint"] == "AQAB..."
    assert kwargs["data"]["duration"] == "180"


@patch("vinyl_recognizer.acoustid.shutil.which", return_value=None)
def test_recognize_returns_none_when_fpcalc_missing(mock_which):
    assert acoustid.recognize(b"wav-bytes", "test-key") is None


@patch("vinyl_recognizer.acoustid.subprocess.run")
@patch("vinyl_recognizer.acoustid.shutil.which", return_value="/usr/bin/fpcalc")
def test_recognize_returns_none_when_fpcalc_fails(mock_which, mock_run):
    mock_run.side_effect = RuntimeError("fpcalc crashed")

    assert acoustid.recognize(b"wav-bytes", "test-key") is None


@patch("vinyl_recognizer.acoustid.requests.post")
@patch("vinyl_recognizer.acoustid.subprocess.run")
@patch("vinyl_recognizer.acoustid.shutil.which", return_value="/usr/bin/fpcalc")
def test_recognize_returns_none_when_no_results(mock_which, mock_run, mock_post):
    mock_run.return_value = _fpcalc_output()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"status": "ok", "results": []}
    mock_post.return_value = mock_response

    assert acoustid.recognize(b"wav-bytes", "test-key") is None


@patch("vinyl_recognizer.acoustid.requests.post")
@patch("vinyl_recognizer.acoustid.subprocess.run")
@patch("vinyl_recognizer.acoustid.shutil.which", return_value="/usr/bin/fpcalc")
def test_recognize_returns_none_on_error_status(mock_which, mock_run, mock_post):
    mock_run.return_value = _fpcalc_output()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"status": "error", "error": {"message": "invalid client"}}
    mock_post.return_value = mock_response

    assert acoustid.recognize(b"wav-bytes", "test-key") is None


@patch("vinyl_recognizer.acoustid.requests.post")
@patch("vinyl_recognizer.acoustid.subprocess.run")
@patch("vinyl_recognizer.acoustid.shutil.which", return_value="/usr/bin/fpcalc")
def test_recognize_returns_none_on_request_exception(mock_which, mock_run, mock_post):
    mock_run.return_value = _fpcalc_output()
    mock_post.side_effect = RuntimeError("network error")

    assert acoustid.recognize(b"wav-bytes", "test-key") is None
