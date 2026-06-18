"""Tests for the Lidarr -> MusicLibrary importer."""

from unittest.mock import MagicMock, patch

from mediainfo.lidarr_import import import_from_lidarr
from mediainfo.musiclibrary import MusicLibrary


def _response(json_data):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data
    return resp


def _artist(id=1, name="Pink Floyd", mbid="83d91898-7763-47d7-b03b-b92132375c47"):
    return {"id": id, "artistName": name, "foreignArtistId": mbid}


def _album(id=1, title="The Wall", mbid="album-mbid"):
    return {"id": id, "title": title, "foreignAlbumId": mbid}


def _track(title="Comfortably Numb", mbid="recording-mbid", album_id=1):
    return {"title": title, "foreignRecordingId": mbid, "albumId": album_id}


def _library(tmp_path):
    return MusicLibrary(str(tmp_path / "library.db"))


@patch("mediainfo.lidarr_import.requests.get")
def test_imports_artist_album_track_mbids(mock_get, tmp_path):
    library = _library(tmp_path)
    mock_get.side_effect = [
        _response([_artist()]),
        _response([_album()]),
        _response([_track()]),
    ]

    stats = import_from_lidarr(library, "http://lidarr.local:6003", "test-key")

    assert stats.artists == 1
    assert stats.albums == 1
    assert stats.tracks == 1
    assert stats.failed_artists == 0

    artist_id = library.get_or_create_artist("Pink Floyd")
    assert library.get_mbid("artist", artist_id) == "83d91898-7763-47d7-b03b-b92132375c47"
    album_id = library.get_or_create_album(artist_id, "The Wall")
    assert library.get_mbid("album", album_id) == "album-mbid"
    track_id = library.get_or_create_track(artist_id, "Comfortably Numb")
    assert library.get_mbid("track", track_id) == "recording-mbid"


@patch("mediainfo.lidarr_import.requests.get")
def test_uses_api_key_header_and_correct_urls(mock_get, tmp_path):
    library = _library(tmp_path)
    mock_get.side_effect = [_response([_artist()]), _response([]), _response([])]

    import_from_lidarr(library, "http://lidarr.local:6003/", "test-key")

    artist_call = mock_get.call_args_list[0]
    assert artist_call.args[0] == "http://lidarr.local:6003/api/v1/artist"
    assert artist_call.kwargs["headers"] == {"X-Api-Key": "test-key"}

    album_call = mock_get.call_args_list[1]
    assert album_call.args[0] == "http://lidarr.local:6003/api/v1/album"
    assert album_call.kwargs["params"] == {"artistId": 1}

    track_call = mock_get.call_args_list[2]
    assert track_call.args[0] == "http://lidarr.local:6003/api/v1/track"
    assert track_call.kwargs["params"] == {"artistId": 1}


@patch("mediainfo.lidarr_import.requests.get")
def test_skips_artist_without_mbid_but_still_creates_entity(mock_get, tmp_path):
    library = _library(tmp_path)
    artist = _artist(mbid="")
    mock_get.side_effect = [_response([artist]), _response([]), _response([])]

    import_from_lidarr(library, "http://lidarr.local:6003", "test-key")

    artist_id = library.get_or_create_artist("Pink Floyd")
    assert library.get_mbid("artist", artist_id) is None


@patch("mediainfo.lidarr_import.requests.get")
def test_continues_after_one_artist_fails(mock_get, tmp_path):
    library = _library(tmp_path)
    mock_get.side_effect = [
        _response([_artist(id=1, name="Pink Floyd"), _artist(id=2, name="Queen", mbid="queen-mbid")]),
        Exception("network error"),  # album fetch for artist 1 fails
        _response([_album()]),       # album fetch for artist 2
        _response([_track()]),       # track fetch for artist 2
    ]

    stats = import_from_lidarr(library, "http://lidarr.local:6003", "test-key")

    assert stats.artists == 1
    assert stats.failed_artists == 1

    queen_id = library.get_or_create_artist("Queen")
    assert library.get_mbid("artist", queen_id) == "queen-mbid"


@patch("mediainfo.lidarr_import.requests.get")
def test_multiple_artists_albums_and_tracks(mock_get, tmp_path):
    library = _library(tmp_path)
    mock_get.side_effect = [
        _response([_artist(id=1, name="Pink Floyd"), _artist(id=2, name="Queen", mbid="queen-mbid")]),
        _response([_album(id=1, title="The Wall"), _album(id=2, title="Animals", mbid="animals-mbid")]),
        _response([
            _track(title="Comfortably Numb", album_id=1),
            _track(title="Money", mbid="money-mbid", album_id=2),
        ]),
        _response([_album(id=3, title="A Night at the Opera", mbid="anato-mbid")]),
        _response([_track(title="Bohemian Rhapsody", mbid="br-mbid", album_id=3)]),
    ]

    stats = import_from_lidarr(library, "http://lidarr.local:6003", "test-key")

    assert stats.artists == 2
    assert stats.albums == 3
    assert stats.tracks == 3

    artist_id = library.get_or_create_artist("Pink Floyd")
    track_id = library.get_or_create_track(artist_id, "Comfortably Numb")
    albums = library.get_albums_for_track(track_id)
    assert [title for _, title, _ in albums] == ["The Wall"]


@patch("mediainfo.lidarr_import.requests.get")
def test_links_track_to_multiple_albums(mock_get, tmp_path):
    library = _library(tmp_path)
    mock_get.side_effect = [
        _response([_artist(id=1, name="Pink Floyd")]),
        _response([
            _album(id=1, title="The Wall", mbid="wall-mbid"),
            _album(id=2, title="Is There Anybody Out There?", mbid="live-mbid"),
        ]),
        _response([
            _track(title="Comfortably Numb", album_id=1),
            _track(title="Comfortably Numb", album_id=2),
        ]),
    ]

    import_from_lidarr(library, "http://lidarr.local:6003", "test-key")

    artist_id = library.get_or_create_artist("Pink Floyd")
    track_id = library.get_or_create_track(artist_id, "Comfortably Numb")
    albums = library.get_albums_for_track(track_id)
    assert sorted(title for _, title, _ in albums) == ["Is There Anybody Out There?", "The Wall"]


@patch("mediainfo.lidarr_import.requests.get")
def test_raises_when_initial_artist_list_fails(mock_get, tmp_path):
    library = _library(tmp_path)
    mock_get.return_value.raise_for_status.side_effect = Exception("connection refused")

    try:
        import_from_lidarr(library, "http://lidarr.local:6003", "test-key")
        assert False, "expected an exception"
    except Exception:
        pass
