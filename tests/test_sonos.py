"""Tests for the Sonos now-playing source."""

from unittest.mock import MagicMock, PropertyMock, patch

from mediainfo.config import SonosConfig
from mediainfo.sources.sonos import SonosSource
from mediainfo.status import AvailabilityReason


def _make_group(coordinator):
    group = MagicMock()
    group.coordinator = coordinator
    return group


def _make_device(
    ip,
    state="PLAYING",
    title="Comfortably Numb",
    artist="Pink Floyd",
    album="The Wall",
    album_art="http://192.168.1.80:1400/cover.jpg",
):
    device = MagicMock()
    device.ip_address = ip
    device.get_current_transport_info.return_value = {"current_transport_state": state}
    device.get_current_track_info.return_value = {
        "title": title,
        "artist": artist,
        "album": album,
        "album_art": album_art,
    }
    return device


@patch("mediainfo.sources.sonos.SoCo")
def test_returns_playing_track(MockSoCo):
    device = _make_device("192.168.1.80")
    MockSoCo.return_value.all_groups = [_make_group(device)]

    source = SonosSource(SonosConfig(enabled=True, speaker_ips=["192.168.1.80"]))
    now_playing = source.get_now_playing()

    assert now_playing.title == "Comfortably Numb"
    assert now_playing.subtitle == "Pink Floyd"
    assert now_playing.album == "The Wall"
    assert now_playing.images[0].url == "http://192.168.1.80:1400/cover.jpg"
    assert now_playing.images[0].label == "Album art (Sonos)"
    assert source.availability_reason == AvailabilityReason.PLAYING


@patch("mediainfo.sources.sonos.SoCo")
def test_returns_none_when_not_playing(MockSoCo):
    device = _make_device("192.168.1.80", state="STOPPED")
    MockSoCo.return_value.all_groups = [_make_group(device)]

    source = SonosSource(SonosConfig(enabled=True, speaker_ips=["192.168.1.80"]))
    result = source.get_now_playing()

    assert result is None
    assert source.availability_reason == AvailabilityReason.IDLE


@patch("mediainfo.sources.sonos.SoCo")
def test_returns_playing_track_when_transitioning(MockSoCo):
    device = _make_device("192.168.1.80", state="TRANSITIONING")
    MockSoCo.return_value.all_groups = [_make_group(device)]

    result = SonosSource(SonosConfig(enabled=True, speaker_ips=["192.168.1.80"])).get_now_playing()

    assert result is not None
    assert result.title == "Comfortably Numb"


@patch("mediainfo.sources.sonos.SoCo")
def test_returns_none_when_title_empty(MockSoCo):
    device = _make_device("192.168.1.80", title="")
    MockSoCo.return_value.all_groups = [_make_group(device)]

    result = SonosSource(SonosConfig(enabled=True, speaker_ips=["192.168.1.80"])).get_now_playing()

    assert result is None


@patch("mediainfo.sources.sonos.SoCo")
def test_checks_all_zones_and_returns_playing_one(MockSoCo):
    idle = _make_device("192.168.1.80", state="STOPPED")
    playing = _make_device("192.168.1.81", title="Money", artist="Pink Floyd")
    MockSoCo.return_value.all_groups = [_make_group(idle), _make_group(playing)]

    now_playing = SonosSource(
        SonosConfig(enabled=True, speaker_ips=["192.168.1.80"])
    ).get_now_playing()

    assert now_playing.title == "Money"


@patch("mediainfo.sources.sonos.SoCo")
def test_deduplicates_same_coordinator(MockSoCo):
    device = _make_device("192.168.1.80")
    # Same coordinator appears in two groups (shouldn't happen in practice, but guard against it)
    MockSoCo.return_value.all_groups = [_make_group(device), _make_group(device)]

    SonosSource(SonosConfig(enabled=True, speaker_ips=["192.168.1.80"])).get_now_playing()

    # Only queried once despite appearing twice
    device.get_current_transport_info.assert_called_once()


@patch("mediainfo.sources.sonos.SoCo")
def test_relative_album_art_url_uses_device_ip(MockSoCo):
    device = _make_device("192.168.1.81", album_art="/getaa?s=1&u=x%3a1")
    MockSoCo.return_value.all_groups = [_make_group(device)]

    now_playing = SonosSource(
        SonosConfig(enabled=True, speaker_ips=["192.168.1.80"])
    ).get_now_playing()

    assert now_playing.images[0].url == "http://192.168.1.81:1400/getaa?s=1&u=x%3a1"


@patch("mediainfo.sources.sonos.SoCo")
def test_blacklist_skips_speaker_by_name(MockSoCo):
    blacklisted = _make_device("192.168.1.80", title="Kitchen Radio")
    blacklisted.player_name = "Kitchen"
    allowed = _make_device("192.168.1.81", title="Money", artist="Pink Floyd")
    allowed.player_name = "Living Room"
    MockSoCo.return_value.all_groups = [_make_group(blacklisted), _make_group(allowed)]

    config = SonosConfig(enabled=True, speaker_ips=["192.168.1.80"], blacklist=["Kitchen"])
    now_playing = SonosSource(config).get_now_playing()

    assert now_playing.title == "Money"


@patch("mediainfo.sources.sonos.SoCo")
def test_blacklist_skips_speaker_by_ip(MockSoCo):
    blacklisted = _make_device("192.168.1.80", title="Kitchen Radio")
    blacklisted.player_name = "Kitchen"
    allowed = _make_device("192.168.1.81", title="Money", artist="Pink Floyd")
    allowed.player_name = "Living Room"
    MockSoCo.return_value.all_groups = [_make_group(blacklisted), _make_group(allowed)]

    config = SonosConfig(enabled=True, speaker_ips=["192.168.1.80"], blacklist=["192.168.1.80"])
    now_playing = SonosSource(config).get_now_playing()

    assert now_playing.title == "Money"


@patch("mediainfo.sources.sonos.SoCo")
def test_blacklist_returns_none_when_only_blacklisted_playing(MockSoCo):
    blacklisted = _make_device("192.168.1.80", title="Kitchen Radio")
    blacklisted.player_name = "Kitchen"
    MockSoCo.return_value.all_groups = [_make_group(blacklisted)]

    config = SonosConfig(enabled=True, speaker_ips=["192.168.1.80"], blacklist=["Kitchen"])
    result = SonosSource(config).get_now_playing()

    assert result is None


@patch("mediainfo.sources.sonos.SoCo")
def test_returns_none_on_exception(MockSoCo):
    # Raises while just discovering groups (SoCo(ip).all_groups itself) -
    # every configured seed effectively didn't answer, same shape as
    # test_returns_none_when_all_seeds_unreachable below.
    type(MockSoCo.return_value).all_groups = PropertyMock(side_effect=RuntimeError("network error"))

    source = SonosSource(SonosConfig(enabled=True, speaker_ips=["192.168.1.80"]))
    result = source.get_now_playing()

    assert result is None
    assert source.last_poll_failed is True
    assert source.availability_reason == AvailabilityReason.NETWORK_UNREACHABLE


@patch("mediainfo.sources.sonos.SoCo")
def test_generic_exception_during_group_processing_sets_api_error(MockSoCo):
    # Unlike discovery failing, this raises *after* groups were
    # successfully discovered - a real integration bug, not "unreachable".
    broken_group = MagicMock()
    type(broken_group).coordinator = PropertyMock(side_effect=RuntimeError("unexpected"))
    MockSoCo.return_value.all_groups = [broken_group]

    source = SonosSource(SonosConfig(enabled=True, speaker_ips=["192.168.1.80"]))
    result = source.get_now_playing()

    assert result is None
    assert source.last_poll_failed is True
    assert source.availability_reason == AvailabilityReason.API_ERROR


@patch("mediainfo.sources.sonos.SoCo")
def test_falls_back_to_next_speaker_when_first_seed_unreachable(MockSoCo):
    playing = _make_device("192.168.1.81", title="Money", artist="Pink Floyd")
    working_seed = MagicMock()
    working_seed.all_groups = [_make_group(playing)]

    def _soco(ip):
        if ip == "192.168.1.80":
            raise RuntimeError("device offline")
        return working_seed

    MockSoCo.side_effect = _soco

    config = SonosConfig(enabled=True, speaker_ips=["192.168.1.80", "192.168.1.81"])
    result = SonosSource(config).get_now_playing()

    assert result is not None
    assert result.title == "Money"


@patch("mediainfo.sources.sonos.SoCo")
def test_returns_none_when_all_seeds_unreachable(MockSoCo):
    MockSoCo.side_effect = RuntimeError("device offline")

    config = SonosConfig(enabled=True, speaker_ips=["192.168.1.80", "192.168.1.81"])
    source = SonosSource(config)
    result = source.get_now_playing()

    assert result is None
    assert source.last_poll_failed is True
    # soco can't tell "speakers off" from a real network blip either - the
    # honest, appropriately-humble read is Warning, not a hard error.
    assert source.availability_reason == AvailabilityReason.NETWORK_UNREACHABLE


@patch("mediainfo.sources.sonos.SoCo")
def test_skips_unsupported_coordinator_and_checks_next(MockSoCo):
    # e.g. a Sonos device that doesn't support GetTransportInfo
    broken = MagicMock()
    broken.ip_address = "192.168.1.82"
    broken.get_current_transport_info.side_effect = RuntimeError("not supported")

    playing = _make_device("192.168.1.80", title="Money", artist="Pink Floyd")
    MockSoCo.return_value.all_groups = [_make_group(broken), _make_group(playing)]

    result = SonosSource(SonosConfig(enabled=True, speaker_ips=["192.168.1.80"])).get_now_playing()

    assert result is not None
    assert result.title == "Money"
