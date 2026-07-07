"""Tests for the Discogs artwork enricher."""

from typing import Any
from unittest.mock import MagicMock, patch

from mediainfo.config import DiscogsConfig
from mediainfo.enrichers.discogs import DiscogsEnricher, _is_real_image
from mediainfo.models import Artwork, NowPlaying
from mediainfo.musiclibrary import MusicLibrary


def _enricher(**kwargs) -> DiscogsEnricher:
    defaults: dict[str, Any] = dict(enabled=True, token="test-token")
    defaults.update(kwargs)
    return DiscogsEnricher(DiscogsConfig(**defaults))


def _song(**kwargs) -> NowPlaying:
    defaults: dict[str, Any] = dict(
        source="sonos",
        media_type="music",
        title="Comfortably Numb",
        subtitle="Pink Floyd",
        album="The Wall",
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def _search_response(results):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"results": results}
    return resp


def _master(cover="https://i.discogs.com/cover.jpg", **kwargs):
    base = {"type": "master", "title": "Pink Floyd - The Wall", "cover_image": cover, "thumb": ""}
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# _is_real_image
# ---------------------------------------------------------------------------

def test_is_real_image_accepts_cdn_url():
    assert _is_real_image("https://i.discogs.com/abc123/image.jpg")


def test_is_real_image_rejects_spacer_gif():
    assert not _is_real_image("https://st.discogs.com/spacer.gif")


def test_is_real_image_rejects_noimage():
    assert not _is_real_image("https://st.discogs.com/noimage.png")


def test_is_real_image_rejects_default_release():
    assert not _is_real_image("https://st.discogs.com/default-release.png")


def test_is_real_image_rejects_empty():
    assert not _is_real_image("")


# ---------------------------------------------------------------------------
# Skips non-music
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.discogs.requests.get")
def test_skips_movie(mock_get):
    np = NowPlaying(source="kodi", media_type="movie", title="Inception")
    _enricher().enrich(np)
    mock_get.assert_not_called()


@patch("mediainfo.enrichers.discogs.requests.get")
def test_skips_episode(mock_get):
    np = NowPlaying(source="kodi", media_type="episode", title="Breaking Bad")
    _enricher().enrich(np)
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Skips when artist or album is missing
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.discogs.requests.get")
def test_skips_when_artist_missing(mock_get):
    np = _song(subtitle="", album="The Wall")
    _enricher().enrich(np)
    mock_get.assert_not_called()


@patch("mediainfo.enrichers.discogs.requests.get")
def test_skips_when_album_missing(mock_get):
    np = _song(album="")
    _enricher().enrich(np)
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path: master found first try
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.discogs.requests.get")
def test_appends_cover_from_master(mock_get):
    mock_get.return_value = _search_response([_master()])
    np = _song()
    _enricher().enrich(np)

    assert len(np.images) == 1
    assert np.images[0].url == "https://i.discogs.com/cover.jpg"
    assert np.images[0].label == "Album art (Discogs)"


@patch("mediainfo.enrichers.discogs.requests.get")
def test_searches_with_correct_params(mock_get):
    mock_get.return_value = _search_response([_master()])
    _enricher().enrich(_song())

    mock_get.assert_called_once_with(
        "https://api.discogs.com/database/search",
        params={
            "type": "master",
            "artist": "Pink Floyd",
            "release_title": "The Wall",
            "token": "test-token",
        },
        headers={"User-Agent": "mediainfo/1.0 (personal use)"},
        timeout=10,
    )


# ---------------------------------------------------------------------------
# Falls back to release search when no master found
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.discogs.requests.get")
def test_falls_back_to_release_when_no_master(mock_get):
    release = {"type": "release", "cover_image": "https://i.discogs.com/rel.jpg", "thumb": ""}
    mock_get.side_effect = [
        _search_response([]),                   # master → empty
        _search_response([release]),            # release → found
    ]
    np = _song()
    _enricher().enrich(np)

    assert len(np.images) == 1
    assert np.images[0].url == "https://i.discogs.com/rel.jpg"
    assert mock_get.call_count == 2
    assert mock_get.call_args_list[1][1]["params"]["type"] == "release"


@patch("mediainfo.enrichers.discogs.requests.get")
def test_no_images_added_when_both_searches_empty(mock_get):
    mock_get.return_value = _search_response([])
    np = _song()
    _enricher().enrich(np)

    assert np.images == []
    assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# Placeholder filtering
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.discogs.requests.get")
def test_skips_placeholder_cover_image_and_uses_next(mock_get):
    results = [
        _master(cover="https://st.discogs.com/spacer.gif"),
        _master(cover="https://i.discogs.com/real.jpg"),
    ]
    mock_get.return_value = _search_response(results)
    np = _song()
    _enricher().enrich(np)

    assert np.images[0].url == "https://i.discogs.com/real.jpg"


@patch("mediainfo.enrichers.discogs.requests.get")
def test_falls_back_to_thumb_when_cover_image_empty(mock_get):
    result = {"type": "master", "cover_image": "", "thumb": "https://i.discogs.com/thumb.jpg"}
    mock_get.return_value = _search_response([result])
    np = _song()
    _enricher().enrich(np)

    assert np.images[0].url == "https://i.discogs.com/thumb.jpg"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.discogs.requests.get")
def test_does_not_add_duplicate_url(mock_get):
    existing_url = "https://i.discogs.com/cover.jpg"
    mock_get.return_value = _search_response([_master(cover=existing_url)])
    np = _song(images=[Artwork(url=existing_url, label="existing")])
    _enricher().enrich(np)

    assert len(np.images) == 1  # not duplicated


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.discogs.requests.get")
def test_request_error_leaves_images_unchanged(mock_get):
    mock_get.side_effect = Exception("network error")
    np = _song()
    _enricher().enrich(np)

    assert np.images == []


@patch("mediainfo.enrichers.discogs.requests.get")
def test_http_error_on_master_falls_through_to_release(mock_get):
    release = {"type": "release", "cover_image": "https://i.discogs.com/rel.jpg", "thumb": ""}
    error_resp = MagicMock()
    error_resp.raise_for_status.side_effect = Exception("429 rate limited")
    mock_get.side_effect = [error_resp, _search_response([release])]

    np = _song()
    _enricher().enrich(np)

    # The master search error is swallowed; release search still ran.
    assert len(np.images) == 1
    assert np.images[0].url == "https://i.discogs.com/rel.jpg"


# ---------------------------------------------------------------------------
# MusicLibrary caching
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.discogs.requests.get")
def test_caches_result_in_library_and_skips_lookup_on_repeat(mock_get, tmp_path):
    library = MusicLibrary(str(tmp_path / "library.db"))
    mock_get.return_value = _search_response([_master()])
    enricher = DiscogsEnricher(DiscogsConfig(enabled=True, token="test-token"), library)

    enricher.enrich(_song())
    assert mock_get.call_count == 1

    np2 = _song()
    enricher.enrich(np2)
    assert mock_get.call_count == 1  # no new network call
    assert np2.images[0].url == "https://i.discogs.com/cover.jpg"


@patch("mediainfo.enrichers.discogs.requests.get")
def test_caches_negative_result_in_library(mock_get, tmp_path):
    library = MusicLibrary(str(tmp_path / "library.db"))
    mock_get.return_value = _search_response([])
    enricher = DiscogsEnricher(DiscogsConfig(enabled=True, token="test-token"), library)

    enricher.enrich(_song())
    assert mock_get.call_count == 2  # master + release search

    enricher.enrich(_song())
    assert mock_get.call_count == 2  # cached miss, no new calls


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------

def test_test_connection_found():
    with patch("mediainfo.enrichers.discogs.find_cover", return_value="https://example.com/x.jpg"):
        ok, message = _enricher().test_connection()
    assert ok is True
    assert "Found" in message


def test_test_connection_no_match_still_reachable():
    with patch("mediainfo.enrichers.discogs.find_cover", return_value=None):
        ok, message = _enricher().test_connection()
    assert ok is True
    assert "no match" in message.lower()


def test_test_connection_handles_exception():
    with patch("mediainfo.enrichers.discogs.find_cover", side_effect=RuntimeError("boom")):
        ok, message = _enricher().test_connection()
    assert ok is False
    assert "boom" in message
