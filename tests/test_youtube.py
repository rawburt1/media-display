"""Tests for the YouTube (Android TV app) ADB "now playing" source."""

from unittest.mock import MagicMock, patch

from mediainfo.config import YoutubeConfig
from mediainfo.sources.youtube import YoutubeSource

# Synthetic `dumpsys media_session` dump: YouTube playing an officially
# distributed track via a "<Artist> - Topic" auto-generated channel.
_YOUTUBE_TOPIC_DUMP = """\
MEDIA SESSION SERVICE (dumpsys media_session)

User Records:
Record for full_user=0
  Sessions Stack - have 1 sessions:
    com.google.android.youtube.tv/MediaButtonReceiver (userId=0)
      package=com.google.android.youtube.tv
      active=true
      state=PlaybackState {state=3, position=12345, buffered position=-1, speed=1.0, updated=1452600117, actions=7339771, custom actions=[], active item id=1, error=null}
      metadata: size=9, description=Bohemian Rhapsody (Official Video), Queen - Topic, null
Audio playback (lastly played comes first)
  uid=10050 packages=com.google.android.youtube.tv
"""

# YouTube playing an official music video, channel isn't a "- Topic" channel,
# but the video title itself follows "<Artist> - <Song>".
_YOUTUBE_ARTIST_TITLE_DUMP = """\
MEDIA SESSION SERVICE (dumpsys media_session)

User Records:
Record for full_user=0
  Sessions Stack - have 1 sessions:
    com.google.android.youtube.tv/MediaButtonReceiver (userId=0)
      package=com.google.android.youtube.tv
      active=true
      state=PlaybackState {state=3, position=12345, buffered position=-1, speed=1.0, updated=1452600117, actions=7339771, custom actions=[], active item id=1, error=null}
      metadata: size=9, description=Daft Punk - One More Time [Official Music Video], Daft Punk, null
Audio playback (lastly played comes first)
  uid=10050 packages=com.google.android.youtube.tv
"""

# YouTube playing a non-music video (a vlog) - should be ignored.
_YOUTUBE_VLOG_DUMP = """\
MEDIA SESSION SERVICE (dumpsys media_session)

User Records:
Record for full_user=0
  Sessions Stack - have 1 sessions:
    com.google.android.youtube.tv/MediaButtonReceiver (userId=0)
      package=com.google.android.youtube.tv
      active=true
      state=PlaybackState {state=3, position=12345, buffered position=-1, speed=1.0, updated=1452600117, actions=7339771, custom actions=[], active item id=1, error=null}
      metadata: size=9, description=My Morning Routine, SomeVlogger, null
Audio playback (lastly played comes first)
  uid=10050 packages=com.google.android.youtube.tv
"""

# Same Topic dump, but paused (state=2, not state=3).
_YOUTUBE_PAUSED_DUMP = _YOUTUBE_TOPIC_DUMP.replace("state=3,", "state=2,")

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
    description = YoutubeSource._find_youtube_description(_YOUTUBE_TOPIC_DUMP)
    assert description == "Bohemian Rhapsody (Official Video), Queen - Topic, null"


def test_ignores_other_apps_session():
    assert YoutubeSource._find_youtube_description(_SPOTIFY_PLAYING_DUMP) is None


def test_ignores_paused_youtube_session():
    assert YoutubeSource._find_youtube_description(_YOUTUBE_PAUSED_DUMP) is None


def test_no_sessions_returns_none():
    assert YoutubeSource._find_youtube_description(_NO_SESSIONS_DUMP) is None


# ---------------------------------------------------------------------------
# _detect_song
# ---------------------------------------------------------------------------

def test_detect_song_via_topic_channel():
    artist, title = YoutubeSource._detect_song(
        "Bohemian Rhapsody (Official Video)", "Queen - Topic"
    )
    assert artist == "Queen"
    assert title == "Bohemian Rhapsody"


def test_detect_song_via_artist_title_in_video_title():
    artist, title = YoutubeSource._detect_song(
        "Daft Punk - One More Time [Official Music Video]", "Daft Punk"
    )
    assert artist == "Daft Punk"
    assert title == "One More Time"


def test_detect_song_returns_none_for_non_music_video():
    artist, title = YoutubeSource._detect_song("My Morning Routine", "SomeVlogger")
    assert artist is None
    assert title is None


def test_detect_song_prefers_topic_channel_over_title_parsing():
    # Title doesn't contain " - " at all, but channel is a Topic channel.
    artist, title = YoutubeSource._detect_song("Bohemian Rhapsody", "Queen - Topic")
    assert artist == "Queen"
    assert title == "Bohemian Rhapsody"


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

def test_get_now_playing_for_topic_channel_song(tmp_path):
    source, _ = _make_source(tmp_path, shell_return=_YOUTUBE_TOPIC_DUMP)

    now_playing = source.get_now_playing()

    assert now_playing.source == "youtube"
    assert now_playing.media_type == "music"
    assert now_playing.title == "Bohemian Rhapsody"
    assert now_playing.subtitle == "Queen"


def test_get_now_playing_for_artist_title_song(tmp_path):
    source, _ = _make_source(tmp_path, shell_return=_YOUTUBE_ARTIST_TITLE_DUMP)

    now_playing = source.get_now_playing()

    assert now_playing.title == "One More Time"
    assert now_playing.subtitle == "Daft Punk"


def test_get_now_playing_returns_none_for_non_music_video(tmp_path):
    source, _ = _make_source(tmp_path, shell_return=_YOUTUBE_VLOG_DUMP)

    assert source.get_now_playing() is None


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
