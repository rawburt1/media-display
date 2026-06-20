"""Tests for the PS5 source."""

from unittest.mock import patch

from mediainfo.config import Ps5Config
from mediainfo.sources.ps5 import Ps5Source


def _source(**kwargs) -> Ps5Source:
    defaults = dict(enabled=True, npsso="test-npsso")
    defaults.update(kwargs)
    with patch("mediainfo.sources.ps5.PSNAWP"):
        return Ps5Source(Ps5Config(**defaults))


def _presence(games):
    return {"basicPresence": {"gameTitleInfoList": games}}


def _ps5_game(**kwargs):
    defaults = {
        "titleName": "Marvel's Spider-Man 2",
        "launchPlatform": "PS5",
        "conceptIconUrl": "https://image.api.playstation.com/concept.png",
    }
    defaults.update(kwargs)
    return defaults


def test_returns_now_playing_for_ps5_game():
    source = _source()
    source._psnawp.user.return_value.get_presence.return_value = _presence([_ps5_game()])

    now_playing = source.get_now_playing()

    assert now_playing.source == "ps5"
    assert now_playing.media_type == "game"
    assert now_playing.title == "Marvel's Spider-Man 2"
    assert now_playing.images[0].url == "https://image.api.playstation.com/concept.png"
    assert now_playing.images[0].label == "Poster (PS5)"


def test_falls_back_to_np_title_icon_url():
    source = _source()
    game = _ps5_game(conceptIconUrl=None, npTitleIconUrl="https://image.api.playstation.com/icon.png")
    source._psnawp.user.return_value.get_presence.return_value = _presence([game])

    now_playing = source.get_now_playing()

    assert now_playing.images[0].url == "https://image.api.playstation.com/icon.png"


def test_no_games_returns_none():
    source = _source()
    source._psnawp.user.return_value.get_presence.return_value = _presence([])

    assert source.get_now_playing() is None


def test_empty_basic_presence_returns_none():
    source = _source()
    source._psnawp.user.return_value.get_presence.return_value = {}

    assert source.get_now_playing() is None


def test_ignores_games_on_other_platforms():
    source = _source()
    game = _ps5_game(launchPlatform="PS4")
    source._psnawp.user.return_value.get_presence.return_value = _presence([game])

    assert source.get_now_playing() is None


def test_picks_ps5_game_among_multiple_platforms():
    source = _source()
    games = [_ps5_game(titleName="PS4 Game", launchPlatform="PS4"), _ps5_game(titleName="PS5 Game")]
    source._psnawp.user.return_value.get_presence.return_value = _presence(games)

    now_playing = source.get_now_playing()

    assert now_playing.title == "PS5 Game"


def test_falls_back_to_format_field_when_launch_platform_missing():
    source = _source()
    game = _ps5_game(launchPlatform=None, format="PS5")
    source._psnawp.user.return_value.get_presence.return_value = _presence([game])

    now_playing = source.get_now_playing()

    assert now_playing.title == "Marvel's Spider-Man 2"


def test_resolves_online_id_only_once():
    source = _source()
    source._psnawp.user.return_value.get_presence.return_value = _presence([])

    source.get_now_playing()
    source.get_now_playing()

    assert source._psnawp.user.call_count == 1


def test_api_error_sets_last_poll_failed():
    source = _source()
    source._psnawp.user.side_effect = RuntimeError("connection refused")

    result = source.get_now_playing()

    assert result is None
    assert source.last_poll_failed is True


def test_successful_poll_clears_last_poll_failed():
    source = _source()
    source._psnawp.user.return_value.get_presence.return_value = _presence([])
    source.last_poll_failed = True

    source.get_now_playing()

    assert source.last_poll_failed is False
