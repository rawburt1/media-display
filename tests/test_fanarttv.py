"""Tests for the fanart.tv artwork enricher."""

from unittest.mock import MagicMock, patch

from mediainfo.config import FanartTvConfig
from mediainfo.enrichers.fanarttv import FanartTvEnricher
from mediainfo.models import Artwork, NowPlaying


def _enricher() -> FanartTvEnricher:
    return FanartTvEnricher(FanartTvConfig(enabled=True, api_key="test-key"))


def _movie(**kwargs) -> NowPlaying:
    defaults = dict(
        source="kodi",
        media_type="movie",
        title="Movie",
        ids={"tmdb": "603"},
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def _episode(**kwargs) -> NowPlaying:
    defaults = dict(
        source="kodi",
        media_type="episode",
        title="Show",
        subtitle="S01E01 - Pilot",
        ids={"tvdb": "121361"},
        season=1,
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


def _song(**kwargs) -> NowPlaying:
    defaults = dict(
        source="kodi",
        media_type="music",
        title="Comfortably Numb",
        subtitle="Pink Floyd",
        ids={"musicbrainzartist": "83d91898-7763-47d7-b03b-b92132375c47", "musicbrainzalbum": "album-mbid"},
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


@patch("mediainfo.enrichers.fanarttv.requests.get")
def test_movie_picks_best_poster_and_background(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "movieposter": [
            {"url": "http://fanart.tv/poster-low.jpg", "lang": "en", "likes": "1"},
            {"url": "http://fanart.tv/poster-high.jpg", "lang": "en", "likes": "10"},
            {"url": "http://fanart.tv/poster-foreign.jpg", "lang": "de", "likes": "999"},
        ],
        "moviebackground": [
            {"url": "http://fanart.tv/background.jpg", "lang": "00", "likes": "5"},
        ],
    }
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    now_playing = _movie()
    _enricher().enrich(now_playing)

    urls = [image.url for image in now_playing.images]
    labels = [image.label for image in now_playing.images]

    assert "http://fanart.tv/poster-high.jpg" in urls
    assert "http://fanart.tv/poster-foreign.jpg" not in urls
    assert "http://fanart.tv/background.jpg" in urls
    assert "Poster (fanart.tv)" in labels
    assert "Fanart (fanart.tv)" in labels

    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args[0] == "https://webservice.fanart.tv/v3/movies/603"
    assert kwargs["params"] == {"api_key": "test-key"}


@patch("mediainfo.enrichers.fanarttv.requests.get")
def test_skips_duplicate_already_in_images(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "movieposter": [
            {"url": "http://existing/poster.jpg", "lang": "en", "likes": "10"},
        ],
        "moviebackground": [],
    }
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    now_playing = _movie(
        images=[Artwork(url="http://existing/poster.jpg", label="Poster (Kodi)")]
    )
    _enricher().enrich(now_playing)

    assert len(now_playing.images) == 1


@patch("mediainfo.enrichers.fanarttv.requests.get")
def test_movie_without_id_does_nothing(mock_get):
    now_playing = _movie(ids={})
    _enricher().enrich(now_playing)

    assert now_playing.images == []
    mock_get.assert_not_called()


@patch("mediainfo.enrichers.fanarttv.requests.get")
def test_episode_matches_season_poster(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "tvposter": [
            {"url": "http://fanart.tv/show-poster.jpg", "lang": "en", "likes": "5"},
        ],
        "seasonposter": [
            {"url": "http://fanart.tv/season1.jpg", "lang": "en", "likes": "5", "season": "1"},
            {"url": "http://fanart.tv/season2.jpg", "lang": "en", "likes": "5", "season": "2"},
        ],
        "showbackground": [
            {"url": "http://fanart.tv/show-background.jpg", "lang": "en", "likes": "5"},
        ],
    }
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    now_playing = _episode(season=1)
    _enricher().enrich(now_playing)

    urls = [image.url for image in now_playing.images]
    labels = [image.label for image in now_playing.images]

    assert "http://fanart.tv/season1.jpg" in urls
    assert "http://fanart.tv/show-poster.jpg" not in urls
    assert "http://fanart.tv/show-background.jpg" in urls
    assert "Season poster (fanart.tv)" in labels
    assert "Fanart (fanart.tv)" in labels

    args, _ = mock_get.call_args
    assert args[0] == "https://webservice.fanart.tv/v3/tv/121361"


@patch("mediainfo.enrichers.fanarttv.requests.get")
def test_episode_falls_back_to_show_poster_without_season_match(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "tvposter": [
            {"url": "http://fanart.tv/show-poster.jpg", "lang": "en", "likes": "5"},
        ],
        "seasonposter": [
            {"url": "http://fanart.tv/season2.jpg", "lang": "en", "likes": "5", "season": "2"},
        ],
        "showbackground": [],
    }
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    now_playing = _episode(season=1)
    _enricher().enrich(now_playing)

    urls = [image.url for image in now_playing.images]
    assert "http://fanart.tv/show-poster.jpg" in urls
    assert "http://fanart.tv/season2.jpg" not in urls


@patch("mediainfo.enrichers.fanarttv.requests.get")
def test_404_response_does_nothing(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response

    now_playing = _movie()
    _enricher().enrich(now_playing)

    assert now_playing.images == []


@patch("mediainfo.enrichers.fanarttv.requests.get")
def test_music_prepends_album_cover(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "name": "Pink Floyd",
        "albums": {
            "album-mbid": {
                "albumcover": [
                    {"url": "http://fanart.tv/album-low.jpg", "likes": "1"},
                    {"url": "http://fanart.tv/album-high.jpg", "likes": "10"},
                ],
            },
            "other-album-mbid": {
                "albumcover": [{"url": "http://fanart.tv/other.jpg", "likes": "100"}],
            },
        },
    }
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    now_playing = _song(
        images=[Artwork(url="http://kodi/album-thumb.jpg", label="Poster (Kodi)")]
    )
    _enricher().enrich(now_playing)

    # fanart.tv's album cover is preferred: shown first.
    assert now_playing.images[0].url == "http://fanart.tv/album-high.jpg"
    assert now_playing.images[0].label == "Album (fanart.tv)"
    assert now_playing.images[1].url == "http://kodi/album-thumb.jpg"

    args, _ = mock_get.call_args
    assert args[0] == "https://webservice.fanart.tv/v3/music/83d91898-7763-47d7-b03b-b92132375c47"


@patch("mediainfo.enrichers.fanarttv.requests.get")
def test_music_without_ids_does_nothing(mock_get):
    now_playing = _song(ids={})
    _enricher().enrich(now_playing)

    assert now_playing.images == []
    mock_get.assert_not_called()


@patch("mediainfo.enrichers.fanarttv.requests.get")
def test_music_without_matching_album_does_nothing(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"albums": {"other-album-mbid": {"albumcover": []}}}
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    now_playing = _song()
    _enricher().enrich(now_playing)

    assert now_playing.images == []


@patch("mediainfo.enrichers.fanarttv.requests.get")
def test_music_resolves_musicbrainz_ids_by_name_when_missing(mock_get):
    mb_response = MagicMock()
    mb_response.status_code = 200
    mb_response.raise_for_status = MagicMock()
    mb_response.json.return_value = {
        "release-groups": [
            {
                "id": "album-mbid",
                "primary-type": "Album",
                "artist-credit": [
                    {"artist": {"id": "83d91898-7763-47d7-b03b-b92132375c47", "name": "Pink Floyd"}}
                ],
            }
        ]
    }

    fanart_response = MagicMock()
    fanart_response.status_code = 200
    fanart_response.raise_for_status = MagicMock()
    fanart_response.json.return_value = {
        "albums": {
            "album-mbid": {"albumcover": [{"url": "http://fanart.tv/album.jpg", "likes": "5"}]},
        }
    }

    mock_get.side_effect = [mb_response, fanart_response]

    # Sonos-style: no musicbrainz ids, just artist (subtitle) + album name.
    now_playing = _song(ids={}, album="The Dark Side of the Moon", source="sonos")
    _enricher().enrich(now_playing)

    assert now_playing.images[0].url == "http://fanart.tv/album.jpg"
    assert now_playing.images[0].label == "Album (fanart.tv)"

    mb_args, mb_kwargs = mock_get.call_args_list[0]
    assert mb_args[0] == "https://musicbrainz.org/ws/2/release-group/"
    assert mb_kwargs["params"]["query"] == 'artist:"Pink Floyd" AND release:"The Dark Side of the Moon"'
    assert "User-Agent" in mb_kwargs["headers"]

    fanart_args, _ = mock_get.call_args_list[1]
    assert fanart_args[0] == "https://webservice.fanart.tv/v3/music/83d91898-7763-47d7-b03b-b92132375c47"


@patch("mediainfo.enrichers.fanarttv.requests.get")
def test_music_without_album_name_does_nothing(mock_get):
    now_playing = _song(ids={}, album="", source="sonos")
    _enricher().enrich(now_playing)

    assert now_playing.images == []
    mock_get.assert_not_called()


@patch("mediainfo.enrichers.fanarttv.requests.get")
def test_music_musicbrainz_no_results_does_nothing(mock_get):
    mb_response = MagicMock()
    mb_response.status_code = 200
    mb_response.raise_for_status = MagicMock()
    mb_response.json.return_value = {"release-groups": []}
    mock_get.return_value = mb_response

    now_playing = _song(ids={}, album="Some Unknown Album", source="sonos")
    _enricher().enrich(now_playing)

    assert now_playing.images == []
    mock_get.assert_called_once()
