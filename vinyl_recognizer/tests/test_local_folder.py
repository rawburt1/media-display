"""Tests for the local-folder fallback recognizer."""

import json
from unittest.mock import MagicMock, patch

from vinyl_recognizer import local_folder


def _fpcalc_output(fingerprint_ints):
    completed = MagicMock()
    completed.stdout = json.dumps(
        {"fingerprint": ",".join(str(x) for x in fingerprint_ints)}
    ).encode()
    return completed


@patch("vinyl_recognizer.local_folder.shutil.which", return_value=None)
def test_recognize_returns_none_when_fpcalc_missing(mock_which):
    assert local_folder.recognize(b"wav-bytes", "/some/folder") is None


def test_recognize_returns_none_when_folder_missing(tmp_path):
    with patch("vinyl_recognizer.local_folder.shutil.which", return_value="/usr/bin/fpcalc"):
        assert local_folder.recognize(b"wav-bytes", str(tmp_path / "missing")) is None


def test_recognize_returns_none_when_folder_empty(tmp_path):
    with patch("vinyl_recognizer.local_folder.shutil.which", return_value="/usr/bin/fpcalc"):
        with patch("vinyl_recognizer.local_folder.subprocess.run") as mock_run:
            mock_run.return_value = _fpcalc_output([1, 2, 3])
            assert local_folder.recognize(b"wav-bytes", str(tmp_path)) is None


def test_recognize_returns_match_above_threshold(tmp_path):
    (tmp_path / "Pink Floyd - Comfortably Numb - The Wall.wav").write_bytes(b"placeholder")
    (tmp_path / "Led Zeppelin - Stairway To Heaven.wav").write_bytes(b"placeholder")

    clip_fp = [1, 2, 3, 4, 5]
    matching_fp = [1, 2, 3, 4, 5]  # identical -> perfect match
    unrelated_fp = [0, 0, 0, 0, 0]  # very different bit pattern

    with patch("vinyl_recognizer.local_folder.shutil.which", return_value="/usr/bin/fpcalc"):
        with patch("vinyl_recognizer.local_folder.subprocess.run") as mock_run:

            def fake_run(args, **kwargs):
                path = args[-1]
                if "Pink Floyd" in path:
                    return _fpcalc_output(matching_fp)
                if "Led Zeppelin" in path:
                    return _fpcalc_output(unrelated_fp)
                return _fpcalc_output(clip_fp)  # the live clip's own tempfile

            mock_run.side_effect = fake_run

            result = local_folder.recognize(b"wav-bytes", str(tmp_path))

    assert result == {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "album": "The Wall",
        "artwork_url": "",
    }


def test_recognize_returns_none_when_below_threshold(tmp_path):
    (tmp_path / "Some Artist - Some Track.wav").write_bytes(b"placeholder")

    with patch("vinyl_recognizer.local_folder.shutil.which", return_value="/usr/bin/fpcalc"):
        with patch("vinyl_recognizer.local_folder.subprocess.run") as mock_run:

            def fake_run(args, **kwargs):
                path = args[-1]
                if "Some Artist" in path:
                    return _fpcalc_output([0, 0, 0, 0])
                return _fpcalc_output([0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF])

            mock_run.side_effect = fake_run

            assert local_folder.recognize(b"wav-bytes", str(tmp_path)) is None


def test_parse_filename_without_album():
    from pathlib import Path

    result = local_folder._parse_filename(Path("Artist - Title.flac"))
    assert result == {"title": "Title", "artist": "Artist", "album": "", "artwork_url": ""}


def test_parse_filename_with_no_separator():
    from pathlib import Path

    result = local_folder._parse_filename(Path("JustATitle.wav"))
    assert result == {"title": "JustATitle", "artist": "", "album": "", "artwork_url": ""}


def test_similarity_identical_fingerprints_is_one():
    assert local_folder._similarity([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0


def test_similarity_finds_best_alignment_offset():
    # b is a shifted by one sample - should still score perfectly once
    # the right offset is tried.
    a = [10, 20, 30, 40, 50]
    b = [0, 10, 20, 30, 40, 50]
    assert local_folder._similarity(a, b) == 1.0


def test_similarity_empty_inputs_is_zero():
    assert local_folder._similarity([], [1, 2, 3]) == 0.0
    assert local_folder._similarity([1, 2, 3], []) == 0.0
