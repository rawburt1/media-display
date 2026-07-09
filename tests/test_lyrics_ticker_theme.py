"""Tests for the Lyrics Ticker theme (mediainfo/themes/lyrics_ticker.py)."""

from mediainfo.config.themes import LyricsTickerConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.themes.lyrics_ticker import LyricsTickerTheme, _parse_lrc

_SAMPLE_LRC = """[ar:Manfred Mann's Earth Band]
[ti:Davy's on the Road Again]

[00:12.50]Davy's on the road again
[00:16.00]Well, you can hear him singing
[00:20.30]Not quite the man he used to be
"""


def _artwork():
    return Artwork(url="https://example.com/art.jpg", label="Album art")


def _music(synced_lyrics="", position=None, duration=None):
    np = NowPlaying(
        source="kodi", media_type="music", title="Davy's on the Road Again",
        subtitle="Manfred Mann's Earth Band", synced_lyrics=synced_lyrics,
    )
    np.position_seconds = position
    np.duration_seconds = duration
    return np


def _movie():
    return NowPlaying(source="kodi", media_type="movie", title="Alien")


# ---------------------------------------------------------------------------
# _parse_lrc
# ---------------------------------------------------------------------------

def test_parse_lrc_extracts_timed_cues_in_order():
    cues = _parse_lrc(_SAMPLE_LRC)
    assert cues == [
        (12.5, "Davy's on the road again"),
        (16.0, "Well, you can hear him singing"),
        (20.3, "Not quite the man he used to be"),
    ]


def test_parse_lrc_skips_metadata_tags_and_blank_lines():
    cues = _parse_lrc("[ar:Someone]\n[ti:Title]\n\n[00:01.00]Only real line")
    assert cues == [(1.0, "Only real line")]


def test_parse_lrc_skips_lines_with_no_text():
    cues = _parse_lrc("[00:01.00]   \n[00:02.00]Real line")
    assert cues == [(2.0, "Real line")]


def test_parse_lrc_sorts_out_of_order_cues():
    cues = _parse_lrc("[00:10.00]second\n[00:01.00]first")
    assert cues == [(1.0, "first"), (10.0, "second")]


def test_parse_lrc_handles_minute_rollover():
    cues = _parse_lrc("[01:05.00]a minute five")
    assert cues == [(65.0, "a minute five")]


def test_parse_lrc_empty_text():
    assert _parse_lrc("") == []


# ---------------------------------------------------------------------------
# prepare() / health_detail()
# ---------------------------------------------------------------------------

def test_music_with_synced_lyrics_returns_cues():
    theme = LyricsTickerTheme()
    now_playing = _music(synced_lyrics=_SAMPLE_LRC, position=15.0, duration=200.0)

    result = theme.prepare(now_playing, _artwork(), None, None, None, LyricsTickerConfig())

    assert len(result.extra_payload["cues"]) == 3
    assert result.extra_payload["cues"][0] == {"t": 12.5, "text": "Davy's on the road again"}
    assert result.extra_payload["position_seconds"] == 15.0
    assert result.extra_payload["duration_seconds"] == 200.0
    assert theme.health_detail(LyricsTickerConfig()) is None


def test_music_without_synced_lyrics_degrades():
    theme = LyricsTickerTheme()
    result = theme.prepare(_music(synced_lyrics=""), _artwork(), None, None, None, LyricsTickerConfig())

    assert result is None
    detail = theme.health_detail(LyricsTickerConfig())
    assert detail["degraded"] is True
    assert "synced lyrics" in detail["reason"]


def test_music_with_unparseable_lyrics_degrades():
    theme = LyricsTickerTheme()
    result = theme.prepare(
        _music(synced_lyrics="just plain unsynced lyrics\nno timestamps here"),
        _artwork(), None, None, None, LyricsTickerConfig(),
    )
    assert result is None
    assert theme.health_detail(LyricsTickerConfig())["degraded"] is True


def test_movie_returns_none_and_clears_degraded_state():
    theme = LyricsTickerTheme()
    theme.prepare(_music(synced_lyrics=""), _artwork(), None, None, None, LyricsTickerConfig())
    assert theme.health_detail(LyricsTickerConfig()) is not None

    result = theme.prepare(_movie(), _artwork(), None, None, None, LyricsTickerConfig())

    assert result is None
    assert theme.health_detail(LyricsTickerConfig()) is None


def test_episode_returns_none():
    theme = LyricsTickerTheme()
    episode = NowPlaying(source="kodi", media_type="episode", title="Breaking Bad")
    result = theme.prepare(episode, _artwork(), None, None, None, LyricsTickerConfig())
    assert result is None


def test_health_detail_none_before_any_prepare_call():
    theme = LyricsTickerTheme()
    assert theme.health_detail(LyricsTickerConfig()) is None


# ---------------------------------------------------------------------------
# client_assets()
# ---------------------------------------------------------------------------

def test_client_assets_registers_theme_handler():
    theme = LyricsTickerTheme()
    assets = theme.client_assets(LyricsTickerConfig())
    assert "window.themeHandlers.lyrics_ticker" in assets.js
    assert "theme-lyrics-ticker" in assets.css


def test_client_assets_falls_back_to_top_for_invalid_position():
    theme = LyricsTickerTheme()
    assets = theme.client_assets(LyricsTickerConfig(position="nonsense; </script>"))
    assert "position-top" in assets.js
    assert "nonsense" not in assets.js


def test_client_assets_includes_configured_position():
    theme = LyricsTickerTheme()
    assets = theme.client_assets(LyricsTickerConfig(position="bottom"))
    assert "position-bottom" in assets.js


def test_client_assets_reflects_show_next_line_toggle():
    theme = LyricsTickerTheme()
    assets_on = theme.client_assets(LyricsTickerConfig(show_next_line=True))
    assert "SHOW_NEXT_LINE = true" in assets_on.js
    assets_off = theme.client_assets(LyricsTickerConfig(show_next_line=False))
    assert "SHOW_NEXT_LINE = false" in assets_off.js
