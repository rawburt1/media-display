"""Tests for the Pexels video source."""

from unittest.mock import MagicMock, patch


from mediainfo.video.pexels import PexelsVideoSource, _best_mp4_url


def _make_file(quality, width, height, file_type="video/mp4"):
    return {"quality": quality, "width": width, "height": height,
            "file_type": file_type, "link": f"https://cdn.pexels.com/{quality}.mp4"}


def _pexels_response(videos):
    mock = MagicMock()
    mock.json.return_value = {"videos": videos}
    mock.raise_for_status.return_value = None
    return mock


def _source(**kwargs):
    defaults = {"api_key": "key123", "queries": "nature", "batch_size": 5}
    defaults.update(kwargs)
    return PexelsVideoSource(**defaults)


@patch("mediainfo.video.pexels.requests.get")
def test_returns_video_clip_from_pexels(mock_get):
    mock_get.return_value = _pexels_response([
        {"video_files": [_make_file("hd", 720, 1280)]},
    ])

    clips = _source().get_videos()

    assert len(clips) == 1
    assert "hd.mp4" in clips[0].url
    assert clips[0].label == "Pexels: nature"


@patch("mediainfo.video.pexels.requests.get")
def test_returns_empty_on_api_error(mock_get):
    mock_get.side_effect = RuntimeError("connection refused")

    clips = _source().get_videos()

    assert clips == []


@patch("mediainfo.video.pexels.requests.get")
def test_returns_empty_on_http_error(mock_get):
    mock_get.return_value = MagicMock(raise_for_status=MagicMock(side_effect=Exception("403")))

    clips = _source().get_videos()

    assert clips == []


@patch("mediainfo.video.pexels.requests.get")
def test_sends_portrait_orientation_param(mock_get):
    mock_get.return_value = _pexels_response([])

    _source().get_videos()

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["orientation"] == "portrait"


@patch("mediainfo.video.pexels.requests.get")
def test_picks_query_from_comma_separated_list(mock_get):
    mock_get.return_value = _pexels_response([])

    _source(queries="nature,ocean,mountains").get_videos()

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["query"] in {"nature", "ocean", "mountains"}


@patch("mediainfo.video.pexels.requests.get")
def test_returns_empty_for_empty_queries(mock_get):
    clips = _source(queries="").get_videos()
    mock_get.assert_not_called()
    assert clips == []


def test_best_mp4_url_prefers_portrait():
    files = [
        _make_file("hd", 1920, 1080),  # landscape
        _make_file("hd", 720, 1280),   # portrait
    ]
    url = _best_mp4_url(files)
    assert url == "https://cdn.pexels.com/hd.mp4"  # second file (portrait hd)


def test_best_mp4_url_prefers_hd_over_sd():
    files = [
        _make_file("sd", 540, 960),
        _make_file("hd", 720, 1280),
    ]
    url = _best_mp4_url(files)
    assert "hd.mp4" in url


def test_best_mp4_url_falls_back_to_landscape_when_no_portrait():
    files = [_make_file("hd", 1920, 1080)]
    url = _best_mp4_url(files)
    assert url is not None


def test_best_mp4_url_skips_non_mp4():
    files = [{"quality": "hd", "width": 720, "height": 1280,
              "file_type": "video/webm", "link": "https://cdn/hd.webm"}]
    url = _best_mp4_url(files)
    assert url is None


def test_best_mp4_url_returns_none_for_empty_list():
    assert _best_mp4_url([]) is None
