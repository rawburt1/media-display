"""Tests for the Wikipedia summary/photo enricher."""

from unittest.mock import MagicMock, patch


from mediainfo.config import WikipediaConfig
from mediainfo.enrichers.wikipedia import WikipediaEnricher
from mediainfo.models import Artwork, NowPlaying


def _config():
    return WikipediaConfig(enabled=True)


def _music(artist="Queen", title="Bohemian Rhapsody", images=None):
    return NowPlaying(
        source="kodi", media_type="music", title=title, subtitle=artist, images=images or []
    )


def _movie(title="Inception", year=2010, images=None):
    return NowPlaying(
        source="kodi", media_type="movie", title=title, year=year, images=images or []
    )


def _episode(show="Breaking Bad", subtitle="Pilot", images=None):
    return NowPlaying(
        source="kodi", media_type="episode", title=show, subtitle=subtitle, images=images or []
    )


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _search_response(title="Queen (band)"):
    return _mock_response({"query": {"search": [{"title": title}]}})


def _summary_response(
    extract="A British rock band.", thumbnail="https://example.com/t.jpg", originalimage=None
):
    data = {"extract": extract}
    if thumbnail:
        data["thumbnail"] = {"source": thumbnail}
    if originalimage:
        data["originalimage"] = {"source": originalimage}
    return _mock_response(data)


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_adds_summary_and_photo_for_music(mock_get):
    mock_get.side_effect = [_search_response(), _summary_response()]
    enricher = WikipediaEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.summary == "A British rock band."
    assert len(np.images) == 1
    assert np.images[0].url == "https://example.com/t.jpg"
    assert "Wikipedia" in np.images[0].label
    assert np.images[0].is_artist_photo is True


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_photo_is_not_marked_artist_photo_for_movie(mock_get):
    mock_get.side_effect = [_search_response(), _summary_response()]
    enricher = WikipediaEnricher(_config())
    np = _movie()

    enricher.enrich(np)

    assert np.images[0].is_artist_photo is False


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_searches_using_artist_for_music(mock_get):
    mock_get.side_effect = [_search_response(), _summary_response()]
    enricher = WikipediaEnricher(_config())

    enricher.enrich(_music(artist="Queen"))

    params = mock_get.call_args_list[0].kwargs["params"]
    assert params["srsearch"] == "Queen"


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_searches_using_title_and_year_for_movie(mock_get):
    mock_get.side_effect = [_search_response("Inception"), _summary_response("A heist movie.")]
    enricher = WikipediaEnricher(_config())

    enricher.enrich(_movie(title="Inception", year=2010))

    params = mock_get.call_args_list[0].kwargs["params"]
    assert params["srsearch"] == "Inception (2010 film)"


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_searches_using_title_without_year_for_movie(mock_get):
    mock_get.side_effect = [_search_response("Inception"), _summary_response("A heist movie.")]
    enricher = WikipediaEnricher(_config())

    enricher.enrich(_movie(title="Inception", year=None))

    params = mock_get.call_args_list[0].kwargs["params"]
    assert params["srsearch"] == "Inception (film)"


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_searches_using_show_title_for_episode(mock_get):
    mock_get.side_effect = [_search_response("Breaking Bad"), _summary_response("A drama series.")]
    enricher = WikipediaEnricher(_config())

    enricher.enrich(_episode(show="Breaking Bad"))

    params = mock_get.call_args_list[0].kwargs["params"]
    assert params["srsearch"] == "Breaking Bad (TV series)"


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_searches_artist_for_episode_with_artist_field(mock_get):
    mock_get.side_effect = [_search_response("Melody Gardot"), _summary_response("A jazz vocalist.")]
    enricher = WikipediaEnricher(_config())
    np = _episode(show="Melody Gardot live på Olympia")
    np.artist = "Melody Gardot"

    enricher.enrich(np)

    params = mock_get.call_args_list[0].kwargs["params"]
    assert params["srsearch"] == "Melody Gardot"
    assert np.summary == "A jazz vocalist."
    assert len(np.images) == 1


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_episode_without_artist_still_searches_tv_series(mock_get):
    mock_get.side_effect = [_search_response("Breaking Bad"), _summary_response("A drama series.")]
    enricher = WikipediaEnricher(_config())
    np = _episode(show="Breaking Bad")
    # artist is "" by default

    enricher.enrich(np)

    params = mock_get.call_args_list[0].kwargs["params"]
    assert params["srsearch"] == "Breaking Bad (TV series)"


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_skips_when_no_artist_for_music(mock_get):
    enricher = WikipediaEnricher(_config())
    np = _music(artist="")

    enricher.enrich(np)

    mock_get.assert_not_called()
    assert np.summary == ""


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_skips_when_no_search_results(mock_get):
    mock_get.return_value = _mock_response({"query": {"search": []}})
    enricher = WikipediaEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.summary == ""
    assert np.images == []


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_summary_404_leaves_now_playing_unchanged(mock_get):
    mock_get.side_effect = [_search_response(), _mock_response({}, status_code=404)]
    enricher = WikipediaEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.summary == ""
    assert np.images == []


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_no_thumbnail_does_not_add_image(mock_get):
    mock_get.side_effect = [_search_response(), _summary_response(thumbnail=None)]
    enricher = WikipediaEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.summary == "A British rock band."
    assert np.images == []


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_prefers_originalimage_over_thumbnail(mock_get):
    # The REST summary's thumbnail is always downsized (~320px wide), which
    # the cache's 640x480 minimum-size filter then rejects on every fetch -
    # the full-resolution originalimage in the same response should win.
    mock_get.side_effect = [
        _search_response(),
        _summary_response(originalimage="https://example.com/original.jpg"),
    ]
    enricher = WikipediaEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.images[0].url == "https://example.com/original.jpg"


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_falls_back_to_thumbnail_when_no_originalimage(mock_get):
    mock_get.side_effect = [_search_response(), _summary_response(originalimage=None)]
    enricher = WikipediaEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.images[0].url == "https://example.com/t.jpg"


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_does_not_add_duplicate_image(mock_get):
    mock_get.side_effect = [_search_response(), _summary_response()]
    enricher = WikipediaEnricher(_config())
    existing = Artwork(url="https://example.com/t.jpg", label="existing")
    np = _music(images=[existing])

    enricher.enrich(np)

    assert len(np.images) == 1


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_handles_network_exception(mock_get):
    mock_get.side_effect = ConnectionError("no network")
    enricher = WikipediaEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.summary == ""
    assert np.images == []


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_falls_back_when_first_result_is_disambiguation(mock_get):
    disambiguation = _mock_response({"type": "disambiguation", "extract": "Queen may refer to..."})
    mock_get.side_effect = [
        _search_response("Queen"),
        disambiguation,
        _search_response("Queen (band)"),
        _summary_response("A British rock band formed in 1970."),
    ]
    enricher = WikipediaEnricher(_config())
    np = _music(artist="Queen")

    enricher.enrich(np)

    assert np.summary == "A British rock band formed in 1970."
    srsearch_calls = [c.kwargs["params"]["srsearch"] for c in mock_get.call_args_list if "params" in c.kwargs]
    assert srsearch_calls == ["Queen", "Queen (band)"]


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_skips_unsupported_media_type(mock_get):
    enricher = WikipediaEnricher(_config())
    np = NowPlaying(source="idle", media_type="wallpaper", title="x", images=[])

    enricher.enrich(np)

    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_second_lookup_for_same_artist_does_not_hit_network(mock_get):
    mock_get.side_effect = [_search_response(), _summary_response()]
    enricher = WikipediaEnricher(_config())

    enricher.enrich(_music(artist="Queen"))
    assert mock_get.call_count == 2

    np2 = _music(artist="Queen", title="A Different Song")
    enricher.enrich(np2)

    assert mock_get.call_count == 2  # no new requests
    assert np2.summary == "A British rock band."
    assert np2.images[0].url == "https://example.com/t.jpg"


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_cache_is_keyed_per_enricher_instance_not_global(mock_get):
    mock_get.side_effect = [_search_response(), _summary_response()]
    WikipediaEnricher(_config()).enrich(_music(artist="Queen"))

    mock_get.side_effect = [_search_response(), _summary_response("A different result.")]
    np = _music(artist="Queen")
    WikipediaEnricher(_config()).enrich(np)

    assert np.summary == "A different result."


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_cache_different_artists_both_hit_network(mock_get):
    mock_get.side_effect = [
        _search_response("Queen (band)"), _summary_response("Queen bio."),
        _search_response("Beatles"), _summary_response("Beatles bio."),
    ]
    enricher = WikipediaEnricher(_config())

    np1 = _music(artist="Queen")
    enricher.enrich(np1)
    np2 = _music(artist="Beatles")
    enricher.enrich(np2)

    assert mock_get.call_count == 4
    assert np1.summary == "Queen bio."
    assert np2.summary == "Beatles bio."


@patch("mediainfo.enrichers.wikipedia.requests.get")
def test_negative_result_is_cached_too(mock_get):
    mock_get.return_value = _mock_response({"query": {"search": []}})
    enricher = WikipediaEnricher(_config())

    enricher.enrich(_music(artist="ZZZ Nonexistent Artist"))
    call_count_after_first = mock_get.call_count

    np2 = _music(artist="ZZZ Nonexistent Artist")
    enricher.enrich(np2)

    assert mock_get.call_count == call_count_after_first  # no retry
    assert np2.summary == ""
    assert np2.images == []
