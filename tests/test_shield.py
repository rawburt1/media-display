"""Tests for the Android TV (Nvidia Shield) ADB "now playing" source."""

from unittest.mock import MagicMock, patch

from mediainfo.config import ShieldConfig
from mediainfo.sources.shield import ShieldSource

# Real `dumpsys media_session` output captured from an Nvidia Shield Pro:
# SVT Play is actively playing live TV, Netflix has a stale, inactive session.
_SVT_PLAY_DUMP = """\
MEDIA SESSION SERVICE (dumpsys media_session)

6 sessions listeners.
Global priority session is null
User Records:
Record for full_user=0
  Volume key long-press listener: null
  Volume key long-press listener package:
  Media key listener: null
  Media key listener package:
  OnMediaKeyEventDispatchedListener: added 0 listener(s)
  OnMediaKeyEventSessionChangedListener: added 1 listener(s)
    from com.android.bluetooth
  Last MediaButtonReceiver: MBR {pi=PendingIntent{3e3d122: PendingIntentRecord{40497b3 se.svt.android.svtplay startForegroundService}}, type=3}
  Media button session is se.svt.android.svtplay/androidx.media3.session.id.50f29227-ec95-48da-8d7a-18bc37c3c000 (userId=0)
  Sessions Stack - have 2 sessions:
    androidx.media3.session.id.50f29227-ec95-48da-8d7a-18bc37c3c000 se.svt.android.svtplay/androidx.media3.session.id.50f29227-ec95-48da-8d7a-18bc37c3c000 (userId=0)
      ownerPid=7574, ownerUid=10109, userId=0
      package=se.svt.android.svtplay
      launchIntent=PendingIntent{39f5170: PendingIntentRecord{132568b se.svt.android.svtplay startActivity (whitelist: f63fd27:+30s0ms)}}
      mediaButtonReceiver=MBR {pi=PendingIntent{3e3d122: PendingIntentRecord{40497b3 se.svt.android.svtplay startForegroundService}}, type=3}
      active=true
      flags=7
      rating type=0
      controllers: 5
      state=PlaybackState {state=3, position=-1, buffered position=-1, speed=0.0, updated=1452600117, actions=7339771, custom actions=[], active item id=5, error=null}
      audioAttrs=AudioAttributes: usage=USAGE_MEDIA content=CONTENT_TYPE_MUSIC flags=0x800 tags= bundle=null
      volumeType=1, controlType=2, max=0, current=0
      metadata: size=9, description=Morgonstudion, Idag 07:00, null
      queueTitle=null, size=6
    Netflix media session com.netflix.ninja/Netflix media session (userId=0)
      ownerPid=4604, ownerUid=10081, userId=0
      package=com.netflix.ninja
      launchIntent=null
      mediaButtonReceiver=null
      active=false
      flags=3
      rating type=0
      controllers: 0
      state=null
      audioAttrs=AudioAttributes: usage=USAGE_MEDIA content=CONTENT_TYPE_UNKNOWN flags=0x800 tags= bundle=null
      volumeType=1, controlType=2, max=0, current=0
      metadata: null
      queueTitle=null, size=0
Audio playback (lastly played comes first)
  uid=10109 packages=se.svt.android.svtplay
"""

# Synthetic dump for a music app reporting title/artist/album.
_SPOTIFY_PLAYING_DUMP = """\
MEDIA SESSION SERVICE (dumpsys media_session)

User Records:
Record for full_user=0
  Sessions Stack - have 1 sessions:
    com.spotify.music/MediaButtonReceiver (userId=0)
      package=com.spotify.music
      active=true
      state=PlaybackState {state=3, position=12345, buffered position=-1, speed=1.0, updated=1452600117, actions=7339771, custom actions=[], active item id=1, error=null}
      metadata: size=9, description=Comfortably Numb, Pink Floyd, The Wall
Audio playback (lastly played comes first)
  uid=10001 packages=com.spotify.music
"""

# Same Spotify session, but paused (state=2, not state=3).
_SPOTIFY_PAUSED_DUMP = _SPOTIFY_PLAYING_DUMP.replace("state=3,", "state=2,")

_NO_SESSIONS_DUMP = """\
MEDIA SESSION SERVICE (dumpsys media_session)

User Records:
Record for full_user=0
  Sessions Stack - have 0 sessions:
Audio playback (lastly played comes first)
"""


def _make_source(tmp_path, shell_return=None, shell_side_effect=None):
    key_path = tmp_path / "shield"
    key_path.write_text("fake-key")

    with (
        patch("mediainfo.sources.adb_base.PythonRSASigner") as mock_signer_cls,
        patch("mediainfo.sources.adb_base.AdbDeviceTcp") as mock_device_cls,
    ):
        mock_signer_cls.FromRSAKeyPath.return_value = MagicMock()
        mock_device = MagicMock()
        mock_device.available = True
        if shell_side_effect is not None:
            mock_device.shell.side_effect = shell_side_effect
        else:
            mock_device.shell.return_value = shell_return
        mock_device_cls.return_value = mock_device

        source = ShieldSource(
            ShieldConfig(enabled=True, host="192.168.1.21", adb_key_path=str(key_path))
        )

    return source, mock_device


def test_parses_active_playing_session():
    description, package = ShieldSource._find_playing_session(_SVT_PLAY_DUMP)
    assert description == "Morgonstudion, Idag 07:00, null"
    assert package == "se.svt.android.svtplay"


def test_no_active_playing_session_returns_none():
    assert ShieldSource._find_playing_session(_SPOTIFY_PAUSED_DUMP) is None


def test_no_sessions_returns_none():
    assert ShieldSource._find_playing_session(_NO_SESSIONS_DUMP) is None


def test_parse_description_without_album():
    assert ShieldSource._parse_description("Morgonstudion, Idag 07:00, null") == (
        "Morgonstudion",
        "Idag 07:00",
        "",
    )


def test_parse_description_with_album():
    assert ShieldSource._parse_description("Comfortably Numb, Pink Floyd, The Wall") == (
        "Comfortably Numb",
        "Pink Floyd",
        "The Wall",
    )


def test_parse_description_title_only():
    assert ShieldSource._parse_description("Just a title") == ("Just a title", "", "")


def test_get_now_playing_for_svt_play_session_is_reported_as_episode(tmp_path):
    # SVT Play is a known video app (_VIDEO_PACKAGES), so the thetvdb
    # enricher gets a chance to look up its title as a TV series - see
    # enrichers/thetvdb.py.
    source, _ = _make_source(tmp_path, shell_return=_SVT_PLAY_DUMP)

    now_playing = source.get_now_playing()

    assert now_playing.source == "shield"
    assert now_playing.media_type == "episode"
    assert now_playing.title == "Morgonstudion"
    assert now_playing.subtitle == "Idag 07:00"
    assert now_playing.album == ""
    assert now_playing.images == []


def test_get_now_playing_for_music_session_includes_album(tmp_path):
    source, _ = _make_source(tmp_path, shell_return=_SPOTIFY_PLAYING_DUMP)

    now_playing = source.get_now_playing()

    assert now_playing.media_type == "music"  # not a known video package
    assert now_playing.title == "Comfortably Numb"
    assert now_playing.subtitle == "Pink Floyd"
    assert now_playing.album == "The Wall"


def test_get_now_playing_returns_none_when_nothing_playing(tmp_path):
    source, _ = _make_source(tmp_path, shell_return=_SPOTIFY_PAUSED_DUMP)

    assert source.get_now_playing() is None


def test_get_now_playing_returns_none_on_shell_error(tmp_path):
    source, mock_device = _make_source(tmp_path, shell_side_effect=RuntimeError("boom"))

    assert source.get_now_playing() is None
    mock_device.close.assert_called_once()
    assert source.last_poll_failed is True


def test_connects_when_not_available(tmp_path):
    source, mock_device = _make_source(tmp_path, shell_return=_NO_SESSIONS_DUMP)
    mock_device.available = False

    source.get_now_playing()

    mock_device.connect.assert_called_once()
