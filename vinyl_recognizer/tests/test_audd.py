"""Tests for the AudD API client."""

from unittest.mock import MagicMock, patch

from vinyl_recognizer import audd


@patch("vinyl_recognizer.audd.requests.post")
def test_recognize_returns_track_with_apple_music_artwork(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "status": "success",
        "result": {
            "title": "Comfortably Numb",
            "artist": "Pink Floyd",
            "album": "The Wall",
            "apple_music": {"artwork": {"url": "https://example.com/{w}x{h}bb.jpg"}},
        },
    }
    mock_post.return_value = mock_response

    result = audd.recognize(b"wav-bytes", "test-key")

    assert result == {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "https://example.com/600x600bb.jpg",
    }

    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.audd.io/"
    assert kwargs["data"]["api_token"] == "test-key"
    assert kwargs["files"]["file"][1] == b"wav-bytes"


@patch("vinyl_recognizer.audd.requests.post")
def test_recognize_falls_back_to_spotify_artwork(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "status": "success",
        "result": {
            "title": "Money",
            "artist": "Pink Floyd",
            "album": "The Dark Side of the Moon",
            "spotify": {"album": {"images": [{"url": "https://spotify.example/cover.jpg"}]}},
        },
    }
    mock_post.return_value = mock_response

    result = audd.recognize(b"wav-bytes", "test-key")

    assert result["artwork_url"] == "https://spotify.example/cover.jpg"


@patch("vinyl_recognizer.audd.requests.post")
def test_recognize_returns_none_when_no_match(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"status": "success", "result": None}
    mock_post.return_value = mock_response

    assert audd.recognize(b"wav-bytes", "test-key") is None


@patch("vinyl_recognizer.audd.requests.post")
def test_recognize_returns_none_on_error_status(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"status": "error", "error": {"error_code": 901}}
    mock_post.return_value = mock_response

    assert audd.recognize(b"wav-bytes", "test-key") is None


@patch("vinyl_recognizer.audd.requests.post")
def test_recognize_returns_none_on_request_exception(mock_post):
    mock_post.side_effect = RuntimeError("network error")

    assert audd.recognize(b"wav-bytes", "test-key") is None
