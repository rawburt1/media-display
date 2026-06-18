"""Tests for the YouTube (Android TV app) ADB "now playing" source."""

from unittest.mock import MagicMock, patch

from mediainfo.config import YoutubeConfig
from mediainfo.sources.youtube import YoutubeSource

# Real `dumpsys media_session` output captured from an Nvidia Shield Pro
# while YouTube TV played a music track. Note the channel is reported as
# the plain artist name ("Phil Collins"), not "Phil Collins - Topic" - an
# earlier version of this source assumed the "- Topic" suffix would be
# present and never matched real-world data.
_YOUTUBE_MUSIC_DUMP = """\
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
  Last MediaButtonReceiver: null
  Media button session is com.google.android.youtube.tv/starboard (userId=0)
  Sessions Stack - have 1 sessions:
    starboard com.google.android.youtube.tv/starboard (userId=0)
      ownerPid=1769, ownerUid=10079, userId=0
      package=com.google.android.youtube.tv
      launchIntent=null
      mediaButtonReceiver=null
      active=true
      flags=3
      rating type=0
      controllers: 5
      state=PlaybackState {state=3, position=787, buffered position=0, speed=1.0, updated=1739869823, actions=379, custom actions=[], active item id=-1, error=null}
      audioAttrs=AudioAttributes: usage=USAGE_MEDIA content=CONTENT_TYPE_UNKNOWN flags=0x800 tags= bundle=null
      volumeType=1, controlType=2, max=0, current=0
      metadata: size=5, description=In the Air Tonight, Phil Collins, null
      queueTitle=null, size=0
Audio playback (lastly played comes first)
  uid=10079 packages=com.google.android.youtube.tv
"""

# YouTube playing a video whose title has an "(Official Video)" decoration.
_YOUTUBE_DECORATED_TITLE_DUMP = """\
MEDIA SESSION SERVICE (dumpsys media_session)

User Records:
Record for full_user=0
  Sessions Stack - have 1 sessions:
    com.google.android.youtube.tv/MediaButtonReceiver (userId=0)
      package=com.google.android.youtube.tv
      active=true
      state=PlaybackState {state=3, position=12345, buffered position=-1, speed=1.0, updated=1452600117, actions=7339771, custom actions=[], active item id=1, error=null}
      metadata: size=9, description=Bohemian Rhapsody (Official Video), Queen, null
Audio playback (lastly played comes first)
  uid=10050 packages=com.google.android.youtube.tv
"""

# Same dump, but paused (state=2, not state=3).
_YOUTUBE_PAUSED_DUMP = _YOUTUBE_MUSIC_DUMP.replace("state=3,", "state=2,")

# A different app (Spotify) is playing - YouTube source should ignore it.
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

_NO_SESSIONS_DUMP = """\
MEDIA SESSION SERVICE (dumpsys media_session)

User Records:
Record for full_user=0
  Sessions Stack - have 0 sessions:
Audio playback (lastly played comes first)
"""


def _make_source(tmp_path, shell_return=None, shell_side_effect=None):
    key_path = tmp_path / "youtube"
    key_path.write_text("fake-key")

    with patch("mediainfo.sources.youtube.PythonRSASigner") as mock_signer_cls, patch(
        "mediainfo.sources.youtube.AdbDeviceTcp"
    ) as mock_device_cls:
        mock_signer_cls.FromRSAKeyPath.return_value = MagicMock()
        mock_device = MagicMock()
        mock_device.available = True
        if shell_side_effect is not None:
            mock_device.shell.side_effect = shell_side_effect
        else:
            mock_device.shell.return_value = shell_return
        mock_device_cls.return_value = mock_device

        source = YoutubeSource(
            YoutubeConfig(enabled=True, host="192.168.1.21", adb_key_path=str(key_path))
        )

    return source, mock_device


# ---------------------------------------------------------------------------
# _find_youtube_description
# ---------------------------------------------------------------------------

def test_finds_description_for_active_youtube_session():
    description = YoutubeSource._find_youtube_description(_YOUTUBE_MUSIC_DUMP)
    assert description == "In the Air Tonight, Phil Collins, null"


def test_ignores_other_apps_session():
    assert YoutubeSource._find_youtube_description(_SPOTIFY_PLAYING_DUMP) is None


def test_ignores_paused_youtube_session():
    assert YoutubeSource._find_youtube_description(_YOUTUBE_PAUSED_DUMP) is None


def test_no_sessions_returns_none():
    assert YoutubeSource._find_youtube_description(_NO_SESSIONS_DUMP) is None


# ---------------------------------------------------------------------------
# _strip_decoration
# ---------------------------------------------------------------------------

def test_strip_decoration_removes_official_video_suffix():
    assert YoutubeSource._strip_decoration("Bohemian Rhapsody (Official Video)") == "Bohemian Rhapsody"


def test_strip_decoration_removes_official_music_video_suffix():
    assert YoutubeSource._strip_decoration("One More Time [Official Music Video]") == "One More Time"


def test_strip_decoration_removes_lyrics_suffix():
    assert YoutubeSource._strip_decoration("Yesterday (Lyrics)") == "Yesterday"


def test_strip_decoration_leaves_plain_title_unchanged():
    assert YoutubeSource._strip_decoration("Yesterday") == "Yesterday"


# ---------------------------------------------------------------------------
# get_now_playing
# ---------------------------------------------------------------------------

def test_get_now_playing_reports_channel_as_subtitle(tmp_path):
    source, _ = _make_source(tmp_path, shell_return=_YOUTUBE_MUSIC_DUMP)

    now_playing = source.get_now_playing()

    assert now_playing.source == "youtube"
    assert now_playing.media_type == "music"
    assert now_playing.title == "In the Air Tonight"
    assert now_playing.subtitle == "Phil Collins"


def test_get_now_playing_strips_decoration_from_title(tmp_path):
    source, _ = _make_source(tmp_path, shell_return=_YOUTUBE_DECORATED_TITLE_DUMP)

    now_playing = source.get_now_playing()

    assert now_playing.title == "Bohemian Rhapsody"
    assert now_playing.subtitle == "Queen"


def test_get_now_playing_reports_any_active_video_not_just_music(tmp_path):
    # YouTube TV doesn't expose a reliable "is this a song" signal (see
    # module docstring), so anything actively playing is reported.
    dump = _SPOTIFY_PLAYING_DUMP.replace("com.spotify.music", "com.google.android.youtube.tv").replace(
        "Comfortably Numb, Pink Floyd, The Wall", "My Morning Routine, SomeVlogger, null"
    )
    source, _ = _make_source(tmp_path, shell_return=dump)

    now_playing = source.get_now_playing()

    assert now_playing.title == "My Morning Routine"
    assert now_playing.subtitle == "SomeVlogger"


def test_get_now_playing_returns_none_when_paused(tmp_path):
    source, _ = _make_source(tmp_path, shell_return=_YOUTUBE_PAUSED_DUMP)

    assert source.get_now_playing() is None


def test_get_now_playing_returns_none_for_other_app(tmp_path):
    source, _ = _make_source(tmp_path, shell_return=_SPOTIFY_PLAYING_DUMP)

    assert source.get_now_playing() is None


def test_get_now_playing_returns_none_on_shell_error(tmp_path):
    source, mock_device = _make_source(tmp_path, shell_side_effect=RuntimeError("boom"))

    assert source.get_now_playing() is None
    mock_device.close.assert_called_once()


def test_connects_when_not_available(tmp_path):
    source, mock_device = _make_source(tmp_path, shell_return=_NO_SESSIONS_DUMP)
    mock_device.available = False

    source.get_now_playing()

    mock_device.connect.assert_called_once()
