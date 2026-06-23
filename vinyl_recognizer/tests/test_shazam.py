"""Tests for the Shazam (shazamio) client."""

from unittest.mock import AsyncMock, patch

from vinyl_recognizer import shazam


@patch("vinyl_recognizer.shazam.Shazam")
def test_recognize_returns_track_with_album_and_artwork(mock_shazam_cls):
    mock_shazam_cls.return_value.recognize = AsyncMock(
        return_value={
            "track": {
                "title": "Comfortably Numb",
                "subtitle": "Pink Floyd",
                "images": {"coverart": "https://example.com/cover.jpg", "coverarthq": ""},
                "sections": [
                    {"type": "SONG", "metadata": [{"title": "Album", "text": "The Wall"}]}
                ],
            }
        }
    )

    result = shazam.recognize(b"wav-bytes")

    assert result == {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "https://example.com/cover.jpg",
    }


@patch("vinyl_recognizer.shazam.Shazam")
def test_recognize_prefers_high_quality_artwork(mock_shazam_cls):
    mock_shazam_cls.return_value.recognize = AsyncMock(
        return_value={
            "track": {
                "title": "Money",
                "subtitle": "Pink Floyd",
                "images": {"coverart": "low.jpg", "coverarthq": "high.jpg"},
            }
        }
    )

    result = shazam.recognize(b"wav-bytes")

    assert result["artwork_url"] == "high.jpg"


@patch("vinyl_recognizer.shazam.Shazam")
def test_recognize_returns_none_when_no_track(mock_shazam_cls):
    mock_shazam_cls.return_value.recognize = AsyncMock(return_value={"matches": []})

    assert shazam.recognize(b"wav-bytes") is None


@patch("vinyl_recognizer.shazam.Shazam")
def test_recognize_returns_none_on_exception(mock_shazam_cls):
    mock_shazam_cls.return_value.recognize = AsyncMock(side_effect=RuntimeError("network error"))

    assert shazam.recognize(b"wav-bytes") is None
