"""Tests for the MusicBrainz Cover Art Archive enricher."""

from unittest.mock import patch

from mediainfo.config import MusicBrainzConfig
from mediainfo.enrichers.musicbrainz import MusicBrainzEnricher, resolve_release_group_ids
from mediainfo.models import Artwork, NowPlaying
from mediainfo.musiclibrary import MusicLibrary


def _config():
    return MusicBrainzConfig(enabled=True)


def _music(**kwargs):
    defaults = dict(
        source="spotify",
        media_type="music",
        title="Bohemian Rhapsody",
        subtitle="Queen",
        album="A Night at the Opera",
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


@patch("mediainfo.enrichers.musicbrainz.requests.head")
def test_enriches_with_known_mbid(mock_head):
    np = _music(ids={"musicbrainzalbum": "known-mbid"})
    mock_head.return_value.status_code = 200
    mock_head.return_value.url = "https://caa.example.com/cover.jpg"

    with patch("mediainfo.enrichers.musicbrainz.requests.get") as mock_get:
        MusicBrainzEnricher(_config()).enrich(np)
        mock_get.assert_not_called()

    assert any("MusicBrainz" in img.label for img in np.images)
    assert np.images[-1].url == "https://caa.example.com/cover.jpg"


@patch("mediainfo.enrichers.musicbrainz.requests.get")
@patch("mediainfo.enrichers.musicbrainz.requests.head")
def test_resolves_mbid_by_artist_and_album(mock_head, mock_get):
    np = _music()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "release-groups": [
            {
                "id": "resolved-mbid",
                "primary-type": "Album",
                "artist-credit": [{"artist": {"id": "artist-mbid"}}],
            }
        ]
    }
    mock_head.return_value.status_code = 200
    mock_head.return_value.url = "https://caa.example.com/resolved.jpg"

    MusicBrainzEnricher(_config()).enrich(np)

    assert any("MusicBrainz" in img.label for img in np.images)


@patch("mediainfo.enrichers.musicbrainz.requests.get")
@patch("mediainfo.enrichers.musicbrainz.requests.head")
def test_prefers_album_type_over_compilation(mock_head, mock_get):
    np = _music()
    mock_get.return_value.json.return_value = {
        "release-groups": [
            {
                "id": "compilation-mbid",
                "primary-type": "Compilation",
                "artist-credit": [{"artist": {"id": "artist-mbid"}}],
            },
            {
                "id": "album-mbid",
                "primary-type": "Album",
                "artist-credit": [{"artist": {"id": "artist-mbid"}}],
            },
        ]
    }
    mock_head.return_value.status_code = 200
    mock_head.return_value.url = "https://caa.example.com/album.jpg"

    MusicBrainzEnricher(_config()).enrich(np)

    called_url = mock_head.call_args[0][0]
    assert "album-mbid" in called_url


@patch("mediainfo.enrichers.musicbrainz.requests.head")
def test_skips_when_caa_returns_404(mock_head):
    np = _music(ids={"musicbrainzalbum": "known-mbid"})
    mock_head.return_value.status_code = 404

    MusicBrainzEnricher(_config()).enrich(np)

    assert not any("MusicBrainz" in img.label for img in np.images)


def test_skips_non_music():
    np = _music(media_type="movie")
    with patch("mediainfo.enrichers.musicbrainz.requests.get") as mock_get:
        MusicBrainzEnricher(_config()).enrich(np)
        mock_get.assert_not_called()


def test_skips_when_no_artist_or_album():
    np = _music(subtitle="", album="")
    with patch("mediainfo.enrichers.musicbrainz.requests.get") as mock_get:
        MusicBrainzEnricher(_config()).enrich(np)
        mock_get.assert_not_called()


@patch("mediainfo.enrichers.musicbrainz.requests.head")
def test_no_duplicate_images(mock_head):
    existing_url = "https://caa.example.com/existing.jpg"
    np = _music(
        ids={"musicbrainzalbum": "mbid"}, images=[Artwork(url=existing_url, label="existing")]
    )
    mock_head.return_value.status_code = 200
    mock_head.return_value.url = existing_url

    MusicBrainzEnricher(_config()).enrich(np)

    assert len(np.images) == 1


# ---------------------------------------------------------------------------
# resolve_release_group_ids - shared MusicLibrary-backed resolution
# ---------------------------------------------------------------------------


@patch("mediainfo.enrichers.musicbrainz.requests.get")
def test_resolve_release_group_ids_caches_result_in_library(mock_get, tmp_path):
    library = MusicLibrary(str(tmp_path / "library.db"))
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "release-groups": [
            {
                "id": "resolved-mbid",
                "primary-type": "Album",
                "artist-credit": [{"artist": {"id": "artist-mbid"}}],
            }
        ]
    }

    first = resolve_release_group_ids(library, "Pink Floyd", "The Wall")
    assert first == ("artist-mbid", "resolved-mbid")
    assert mock_get.call_count == 1

    second = resolve_release_group_ids(library, "Pink Floyd", "The Wall")
    assert second == ("artist-mbid", "resolved-mbid")
    assert mock_get.call_count == 1  # no new network call


@patch("mediainfo.enrichers.musicbrainz.requests.get")
def test_resolve_release_group_ids_caches_negative_result(mock_get, tmp_path):
    library = MusicLibrary(str(tmp_path / "library.db"))
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"release-groups": []}

    assert resolve_release_group_ids(library, "Unknown Artist", "Unknown Album") is None
    assert mock_get.call_count == 1

    assert resolve_release_group_ids(library, "Unknown Artist", "Unknown Album") is None
    assert mock_get.call_count == 1  # cached miss, no new call


def test_resolve_release_group_ids_without_library_skips_caching():
    with patch("mediainfo.enrichers.musicbrainz.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "release-groups": [
                {
                    "id": "resolved-mbid",
                    "primary-type": "Album",
                    "artist-credit": [{"artist": {"id": "artist-mbid"}}],
                }
            ]
        }
        resolve_release_group_ids(None, "Pink Floyd", "The Wall")
        resolve_release_group_ids(None, "Pink Floyd", "The Wall")
        assert mock_get.call_count == 2  # no library, so no caching


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


def test_test_connection_success():
    with patch(
        "mediainfo.enrichers.musicbrainz._query_musicbrainz",
        return_value=("artist-mbid", "album-mbid"),
    ):
        ok, message = MusicBrainzEnricher(_config()).test_connection()
    assert ok is True


def test_test_connection_failure():
    with patch("mediainfo.enrichers.musicbrainz._query_musicbrainz", return_value=None):
        ok, message = MusicBrainzEnricher(_config()).test_connection()
    assert ok is False


def test_test_connection_handles_exception():
    with patch(
        "mediainfo.enrichers.musicbrainz._query_musicbrainz", side_effect=RuntimeError("boom")
    ):
        ok, message = MusicBrainzEnricher(_config()).test_connection()
    assert ok is False
    assert "boom" in message
