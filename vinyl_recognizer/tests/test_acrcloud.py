"""Tests for the ACRCloud API client."""

import pytest
from unittest.mock import MagicMock, patch

from vinyl_recognizer import acrcloud


@patch("vinyl_recognizer.acrcloud.requests.post")
def test_recognize_returns_track_with_spotify_artwork(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "status": {"code": 0, "msg": "Success"},
        "metadata": {
            "music": [
                {
                    "title": "Comfortably Numb",
                    "artists": [{"name": "Pink Floyd"}],
                    "album": {"name": "The Wall"},
                    "external_metadata": {
                        "spotify": {"album": {"images": [{"url": "https://example.com/cover.jpg"}]}},
                    },
                }
            ]
        },
    }
    mock_post.return_value = mock_response

    result = acrcloud.recognize(b"wav-bytes", "host.acrcloud.com", "key", "secret")

    assert result == {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "https://example.com/cover.jpg",
    }

    args, kwargs = mock_post.call_args
    assert args[0] == "https://host.acrcloud.com/v1/identify"
    assert kwargs["data"]["access_key"] == "key"
    assert kwargs["data"]["data_type"] == "audio"
    assert kwargs["files"]["sample"][1] == b"wav-bytes"


@patch("vinyl_recognizer.acrcloud.requests.post")
def test_recognize_falls_back_to_deezer_artwork(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "status": {"code": 0, "msg": "Success"},
        "metadata": {
            "music": [
                {
                    "title": "Money",
                    "artists": [{"name": "Pink Floyd"}],
                    "album": {"name": "The Dark Side of the Moon"},
                    "external_metadata": {
                        "deezer": {"album": {"cover_xl": "https://deezer.example/cover.jpg"}},
                    },
                }
            ]
        },
    }
    mock_post.return_value = mock_response

    result = acrcloud.recognize(b"wav-bytes", "host.acrcloud.com", "key", "secret")

    assert result["artwork_url"] == "https://deezer.example/cover.jpg"


@patch("vinyl_recognizer.acrcloud.requests.post")
def test_recognize_returns_none_when_no_result_found(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"status": {"code": 1001, "msg": "No result"}}
    mock_post.return_value = mock_response

    assert acrcloud.recognize(b"wav-bytes", "host.acrcloud.com", "key", "secret") is None


@patch("vinyl_recognizer.acrcloud.requests.post")
def test_recognize_returns_none_on_error_status(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"status": {"code": 3001, "msg": "Invalid signature"}}
    mock_post.return_value = mock_response

    assert acrcloud.recognize(b"wav-bytes", "host.acrcloud.com", "key", "secret") is None


@patch("vinyl_recognizer.acrcloud.requests.post")
def test_recognize_returns_none_on_request_exception(mock_post):
    mock_post.side_effect = RuntimeError("network error")

    assert acrcloud.recognize(b"wav-bytes", "host.acrcloud.com", "key", "secret") is None


@patch("vinyl_recognizer.acrcloud.requests.post")
def test_recognize_raises_rate_limited_on_http_429(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.text = "Too Many Requests"
    mock_post.return_value = mock_response

    with pytest.raises(acrcloud.RateLimitedError):
        acrcloud.recognize(b"wav-bytes", "host.acrcloud.com", "key", "secret")


@patch("vinyl_recognizer.acrcloud.requests.post")
def test_recognize_raises_rate_limited_on_limit_status_message(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"status": {"code": 3003, "msg": "Limit Exceeded"}}
    mock_post.return_value = mock_response

    with pytest.raises(acrcloud.RateLimitedError):
        acrcloud.recognize(b"wav-bytes", "host.acrcloud.com", "key", "secret")
