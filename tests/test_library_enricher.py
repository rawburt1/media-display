"""Tests for the local-library album art enricher."""

from unittest.mock import patch

from mediainfo.enrichers.library import LibraryEnricher
from mediainfo.models import NowPlaying
from mediainfo.musiclibrary import MusicLibrary


def _library(tmp_path):
    return MusicLibrary(str(tmp_path / "library.db"))


def _song(**kwargs):
    defaults = dict(
        source="youtube", media_type="music",
        title="Comfortably Numb", subtitle="Pink Floyd", album="",
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def _seed_track_with_album(library, artist="Pink Floyd", title="Comfortably Numb",
                            album="The Wall", mbid="wall-mbid"):
    artist_id = library.get_or_create_artist(artist)
    track_id = library.get_or_create_track(artist_id, title)
    album_id = library.get_or_create_album(artist_id, album)
    if mbid:
        library.set_mbid("album", album_id, mbid)
    library.link_track_album(track_id, album_id)
    return artist_id, track_id, album_id


@patch("mediainfo.enrichers.library.fetch_front_cover")
def test_adds_album_art_for_matched_track(mock_fetch, tmp_path):
    library = _library(tmp_path)
    _seed_track_with_album(library)
    mock_fetch.return_value = "https://caa.example.com/wall.jpg"

    np = _song()
    LibraryEnricher(library=library).enrich(np)

    assert np.album == "The Wall"
    assert len(np.images) == 1
    assert np.images[0].url == "https://caa.example.com/wall.jpg"
    assert "Library" in np.images[0].label


@patch("mediainfo.enrichers.library.fetch_front_cover")
def test_adds_art_for_all_albums_when_song_on_multiple(mock_fetch, tmp_path):
    library = _library(tmp_path)
    artist_id = library.get_or_create_artist("Pink Floyd")
    track_id = library.get_or_create_track(artist_id, "Comfortably Numb")

    wall_id = library.get_or_create_album(artist_id, "The Wall")
    library.set_mbid("album", wall_id, "wall-mbid")
    library.link_track_album(track_id, wall_id)

    live_id = library.get_or_create_album(artist_id, "Is There Anybody Out There?")
    library.set_mbid("album", live_id, "live-mbid")
    library.link_track_album(track_id, live_id)

    mock_fetch.side_effect = lambda mbid: f"https://caa.example.com/{mbid}.jpg"

    np = _song()
    LibraryEnricher(library=library).enrich(np)

    assert len(np.images) == 2
    urls = {img.url for img in np.images}
    assert urls == {"https://caa.example.com/wall-mbid.jpg", "https://caa.example.com/live-mbid.jpg"}
    # Album name is ambiguous with multiple matches - left for the source to decide.
    assert np.album == ""


@patch("mediainfo.enrichers.library.fetch_front_cover")
def test_skips_album_without_mbid(mock_fetch, tmp_path):
    library = _library(tmp_path)
    _seed_track_with_album(library, mbid=None)

    np = _song()
    LibraryEnricher(library=library).enrich(np)

    assert np.images == []
    mock_fetch.assert_not_called()


def test_does_nothing_when_artist_not_in_library(tmp_path):
    library = _library(tmp_path)
    np = _song()
    LibraryEnricher(library=library).enrich(np)
    assert np.images == []
    assert np.album == ""


def test_does_nothing_when_track_not_in_library(tmp_path):
    library = _library(tmp_path)
    library.get_or_create_artist("Pink Floyd")
    np = _song()
    LibraryEnricher(library=library).enrich(np)
    assert np.images == []


def test_does_nothing_when_album_already_known(tmp_path):
    library = _library(tmp_path)
    _seed_track_with_album(library)

    with patch("mediainfo.enrichers.library.fetch_front_cover") as mock_fetch:
        np = _song(album="Already Known")
        LibraryEnricher(library=library).enrich(np)
        mock_fetch.assert_not_called()
    assert np.images == []


def test_does_nothing_without_library():
    np = _song()
    LibraryEnricher(library=None).enrich(np)
    assert np.images == []


def test_does_nothing_for_non_music(tmp_path):
    library = _library(tmp_path)
    _seed_track_with_album(library)
    np = _song(media_type="movie", title="Comfortably Numb", subtitle="Pink Floyd")
    LibraryEnricher(library=library).enrich(np)
    assert np.images == []


@patch("mediainfo.enrichers.library.fetch_front_cover")
def test_does_not_add_duplicate_url(mock_fetch, tmp_path):
    from mediainfo.models import Artwork

    library = _library(tmp_path)
    _seed_track_with_album(library)
    mock_fetch.return_value = "https://caa.example.com/wall.jpg"

    np = _song(images=[Artwork(url="https://caa.example.com/wall.jpg", label="existing")])
    LibraryEnricher(library=library).enrich(np)

    assert len(np.images) == 1


def test_test_connection_no_network_needed():
    ok, message = LibraryEnricher().test_connection()
    assert ok is True
    assert "no network" in message.lower()
