"""Tests for the Pixabay video source."""

from unittest.mock import MagicMock, patch

from mediainfo.video.pixabay import PixabayVideoSource, _best_url


def _make_video(width, height, url="https://cdn.pixabay.com/video.mp4"):
    return {"url": url, "width": width, "height": height}


def _pixabay_response(hits):
    mock = MagicMock()
    mock.json.return_value = {"hits": hits}
    mock.raise_for_status.return_value = None
    return mock


def _source(**kwargs):
    defaults = {"api_key": "key123", "queries": "nature", "batch_size": 5}
    defaults.update(kwargs)
    return PixabayVideoSource(**defaults)


@patch("mediainfo.video.pixabay.requests.get")
def test_returns_video_clip_from_pixabay(mock_get):
    mock_get.return_value = _pixabay_response(
        [
            {"videos": {"large": _make_video(720, 1280)}},
        ]
    )

    clips = _source().get_videos()

    assert len(clips) == 1
    assert clips[0].url == "https://cdn.pixabay.com/video.mp4"
    assert clips[0].label == "Pixabay: nature"


@patch("mediainfo.video.pixabay.requests.get")
def test_returns_empty_on_api_error(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")

    clips = _source().get_videos()

    assert clips == []


@patch("mediainfo.video.pixabay.requests.get")
def test_returns_empty_on_http_error(mock_get):
    mock_get.return_value = MagicMock(raise_for_status=MagicMock(side_effect=Exception("403")))

    clips = _source().get_videos()

    assert clips == []


@patch("mediainfo.video.pixabay.requests.get")
def test_sends_vertical_orientation_param(mock_get):
    mock_get.return_value = _pixabay_response([])

    _source().get_videos()

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["orientation"] == "vertical"


@patch("mediainfo.video.pixabay.requests.get")
def test_picks_query_from_comma_separated_list(mock_get):
    mock_get.return_value = _pixabay_response([])

    _source(queries="nature,ocean,mountains").get_videos()

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["q"] in {"nature", "ocean", "mountains"}


@patch("mediainfo.video.pixabay.requests.get")
def test_returns_empty_for_empty_queries(mock_get):
    clips = _source(queries="").get_videos()
    mock_get.assert_not_called()
    assert clips == []


@patch("mediainfo.video.pixabay.requests.get")
def test_per_page_capped_at_pixabay_max(mock_get):
    mock_get.return_value = _pixabay_response([])

    _source(batch_size=50).get_videos()

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["per_page"] == 20


def test_best_url_prefers_portrait():
    videos = {
        "large": _make_video(1920, 1080, "https://cdn/landscape.mp4"),
        "medium": _make_video(720, 1280, "https://cdn/portrait.mp4"),
    }
    assert _best_url(videos) == "https://cdn/portrait.mp4"


def test_best_url_prefers_larger_size_among_portrait():
    videos = {
        "large": _make_video(720, 1280, "https://cdn/large.mp4"),
        "small": _make_video(480, 854, "https://cdn/small.mp4"),
    }
    assert _best_url(videos) == "https://cdn/large.mp4"


def test_best_url_falls_back_to_landscape_when_no_portrait():
    videos = {"large": _make_video(1920, 1080, "https://cdn/landscape.mp4")}
    assert _best_url(videos) == "https://cdn/landscape.mp4"


def test_best_url_returns_none_for_empty_dict():
    assert _best_url({}) is None
