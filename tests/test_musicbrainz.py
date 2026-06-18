"""Tests for the MusicBrainz Cover Art Archive enricher."""

from unittest.mock import patch

from mediainfo.config import MusicBrainzConfig
from mediainfo.enrichers.musicbrainz import MusicBrainzEnricher
from mediainfo.models import Artwork, NowPlaying


def _config():
    return MusicBrainzConfig(enabled=True)


def _music(**kwargs):
    defaults = dict(source="spotify", media_type="music",
                    title="Bohemian Rhapsody", subtitle="Queen",
                    album="A Night at the Opera")
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
        "release-groups": [{"id": "resolved-mbid", "primary-type": "Album"}]
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
            {"id": "compilation-mbid", "primary-type": "Compilation"},
            {"id": "album-mbid", "primary-type": "Album"},
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
    np = _music(ids={"musicbrainzalbum": "mbid"},
                images=[Artwork(url=existing_url, label="existing")])
    mock_head.return_value.status_code = 200
    mock_head.return_value.url = existing_url

    MusicBrainzEnricher(_config()).enrich(np)

    assert len(np.images) == 1
