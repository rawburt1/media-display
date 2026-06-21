"""Tests for the dashboard UI's test-connection logic."""

from unittest.mock import MagicMock, patch

from mediainfo.models import NowPlaying
from mediainfo.outputs.config_dashboard import (
    test_enricher as check_enricher,
    test_output as check_output,
    test_source as check_source,
)

# ---------------------------------------------------------------------------
# test_source
# ---------------------------------------------------------------------------


class _FakeSource:
    last_call = None

    def __init__(self, config):
        self.config = config
        self.last_poll_failed = False

    def get_now_playing(self):
        return None


def test_source_unknown_name_returns_false():
    ok, message = check_source("nonexistent", MagicMock())
    assert ok is False
    assert "Unknown" in message


def test_source_none_config_returns_false():
    with patch("mediainfo.__main__.SOURCE_CLASSES", {"fake": _FakeSource}):
        ok, message = check_source("fake", None)
    assert ok is False


def test_source_connected_with_now_playing():
    class _Source(_FakeSource):
        def get_now_playing(self):
            return NowPlaying(source="fake", media_type="music", title="Bohemian Rhapsody")

    with patch("mediainfo.__main__.SOURCE_CLASSES", {"fake": _Source}):
        ok, message = check_source("fake", MagicMock())

    assert ok is True
    assert "Bohemian Rhapsody" in message


def test_source_connected_with_nothing_playing():
    with patch("mediainfo.__main__.SOURCE_CLASSES", {"fake": _FakeSource}):
        ok, message = check_source("fake", MagicMock())

    assert ok is True
    assert "nothing currently playing" in message


def test_source_reports_last_poll_failed():
    class _Source(_FakeSource):
        def get_now_playing(self):
            self.last_poll_failed = True
            return None

    with patch("mediainfo.__main__.SOURCE_CLASSES", {"fake": _Source}):
        ok, message = check_source("fake", MagicMock())

    assert ok is False
    assert "connect" in message.lower()


def test_source_exception_is_caught():
    class _Source(_FakeSource):
        def get_now_playing(self):
            raise RuntimeError("boom")

    with patch("mediainfo.__main__.SOURCE_CLASSES", {"fake": _Source}):
        ok, message = check_source("fake", MagicMock())

    assert ok is False
    assert "boom" in message


def test_source_cleans_up_background_loop():
    fake_loop = MagicMock()

    class _Source(_FakeSource):
        def __init__(self, config):
            super().__init__(config)
            self._loop = fake_loop

    with patch("mediainfo.__main__.SOURCE_CLASSES", {"fake": _Source}):
        check_source("fake", MagicMock())

    fake_loop.call_soon_threadsafe.assert_called_once()


# ---------------------------------------------------------------------------
# test_enricher
# ---------------------------------------------------------------------------


def test_enricher_none_config_returns_false():
    ok, message = check_enricher("thetvdb", None)
    assert ok is False
    assert "Unknown" in message


def test_enricher_unknown_name_returns_false():
    ok, message = check_enricher("nonexistent", MagicMock())
    assert ok is False


def test_enricher_thetvdb_success():
    with patch("mediainfo.enrichers.thetvdb.TheTvDbEnricher._login", return_value="tok"):
        ok, message = check_enricher("thetvdb", MagicMock())
    assert ok is True
    assert "Logged in" in message


def test_enricher_thetvdb_failure():
    with patch("mediainfo.enrichers.thetvdb.TheTvDbEnricher._login", return_value=None):
        ok, message = check_enricher("thetvdb", MagicMock())
    assert ok is False


def test_enricher_fanarttv_success():
    with patch("mediainfo.enrichers.fanarttv.FanartTvEnricher._get", return_value={"x": 1}):
        ok, message = check_enricher("fanarttv", MagicMock())
    assert ok is True


def test_enricher_fanarttv_failure():
    with patch("mediainfo.enrichers.fanarttv.FanartTvEnricher._get", return_value=None):
        ok, message = check_enricher("fanarttv", MagicMock())
    assert ok is False


def test_enricher_tmdb_success():
    with patch("mediainfo.enrichers.tmdb.TmdbEnricher._fetch_rating", return_value=8.7):
        ok, message = check_enricher("tmdb", MagicMock())
    assert ok is True
    assert "8.7" in message


def test_enricher_tmdb_failure():
    with patch("mediainfo.enrichers.tmdb.TmdbEnricher._fetch_rating", return_value=None):
        ok, message = check_enricher("tmdb", MagicMock())
    assert ok is False
    assert "api_key" in message


def test_enricher_omdb_success():
    with patch("mediainfo.enrichers.omdb.OmdbEnricher._fetch", return_value=8.7):
        ok, message = check_enricher("omdb", MagicMock())
    assert ok is True
    assert "8.7" in message


def test_enricher_omdb_failure():
    with patch("mediainfo.enrichers.omdb.OmdbEnricher._fetch", return_value=None):
        ok, message = check_enricher("omdb", MagicMock())
    assert ok is False
    assert "api_key" in message


def test_enricher_discogs_found():
    with patch(
        "mediainfo.enrichers.discogs.DiscogsEnricher._find_cover",
        return_value="https://example.com/x.jpg",
    ):
        ok, message = check_enricher("discogs", MagicMock())
    assert ok is True
    assert "Found" in message


def test_enricher_discogs_no_match_still_reachable():
    with patch("mediainfo.enrichers.discogs.DiscogsEnricher._find_cover", return_value=None):
        ok, message = check_enricher("discogs", MagicMock())
    assert ok is True
    assert "no match" in message.lower()


def test_enricher_lastfm():
    with patch(
        "mediainfo.enrichers.lastfm.LastFmEnricher._fetch_artist_image",
        return_value="https://example.com/x.jpg",
    ):
        ok, message = check_enricher("lastfm", MagicMock())
    assert ok is True
    assert "Found" in message


def test_enricher_musicbrainz_success():
    with patch(
        "mediainfo.enrichers.musicbrainz._query_musicbrainz",
        return_value=("artist-mbid", "album-mbid"),
    ):
        ok, message = check_enricher("musicbrainz", MagicMock())
    assert ok is True


def test_enricher_musicbrainz_failure():
    with patch("mediainfo.enrichers.musicbrainz._query_musicbrainz", return_value=None):
        ok, message = check_enricher("musicbrainz", MagicMock())
    assert ok is False


def test_enricher_wikipedia_success():
    with patch(
        "mediainfo.enrichers.wikipedia.WikipediaEnricher._lookup",
        return_value=("summary text", None),
    ):
        ok, message = check_enricher("wikipedia", MagicMock())
    assert ok is True


def test_enricher_library_no_network_needed():
    ok, message = check_enricher("library", MagicMock())
    assert ok is True


def test_enricher_handles_exception():
    with patch(
        "mediainfo.enrichers.thetvdb.TheTvDbEnricher._login", side_effect=RuntimeError("boom")
    ):
        ok, message = check_enricher("thetvdb", MagicMock())
    assert ok is False
    assert "boom" in message


# ---------------------------------------------------------------------------
# test_output
# ---------------------------------------------------------------------------


def test_output_pixoo_reachable():
    with patch("mediainfo.outputs.config_dashboard._tcp_check", return_value=(True, "ok")) as m:
        ok, message = check_output("pixoo", {"type": "pixoo", "ip": "192.168.1.32"})
    assert ok is True
    m.assert_called_once_with("192.168.1.32", 80)


def test_output_pixoo_missing_address():
    ok, message = check_output("pixoo", {"type": "pixoo"})
    assert ok is False
    assert "No ip" in message


def test_output_nest_hub_uses_cast_port_default():
    with patch("mediainfo.outputs.config_dashboard._tcp_check", return_value=(True, "ok")) as m:
        check_output("nest_hub", {"type": "nest_hub", "device_ip": "192.168.1.41"})
    m.assert_called_once_with("192.168.1.41", 8009)


def test_output_mqtt_uses_host_and_port():
    with patch("mediainfo.outputs.config_dashboard._tcp_check", return_value=(True, "ok")) as m:
        check_output("mqtt", {"type": "mqtt", "host": "broker.local", "port": 1883})
    m.assert_called_once_with("broker.local", 1883)


def test_output_mqtt_missing_fields():
    ok, message = check_output("mqtt", {"type": "mqtt"})
    assert ok is False


def test_output_folder_writable(tmp_path):
    ok, message = check_output("folder", {"type": "folder", "dir": str(tmp_path)})
    assert ok is True
    assert "writable" in message


def test_output_folder_missing_dir():
    ok, message = check_output("folder", {"type": "folder"})
    assert ok is False


def test_output_self_hosted_uses_http_check():
    with patch(
        "mediainfo.outputs.config_dashboard._http_check", return_value=(True, "HTTP 200")
    ) as m:
        ok, message = check_output("web", {"type": "web", "port": 8090})
    assert ok is True
    m.assert_called_once_with("127.0.0.1", 8090)


def test_output_self_hosted_missing_port():
    ok, message = check_output("web", {"type": "web"})
    assert ok is False


def test_output_unknown_type():
    ok, message = check_output("unknown_type", {"type": "unknown_type"})
    assert ok is False
    assert "No connection test" in message


def test_output_exception_is_caught():
    with patch("mediainfo.outputs.config_dashboard._tcp_check", side_effect=RuntimeError("boom")):
        ok, message = check_output("pixoo", {"type": "pixoo", "ip": "1.2.3.4"})
    assert ok is False
    assert "boom" in message


# ---------------------------------------------------------------------------
# _tcp_check / _http_check (real socket/HTTP behavior, mocked at the lowest level)
# ---------------------------------------------------------------------------


def test_tcp_check_success():
    from mediainfo.outputs.config_dashboard import _tcp_check

    with patch("socket.create_connection") as mock_conn:
        mock_conn.return_value.__enter__ = MagicMock()
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        ok, message = _tcp_check("192.168.1.1", 80)

    assert ok is True
    assert "192.168.1.1:80" in message


def test_tcp_check_failure():
    from mediainfo.outputs.config_dashboard import _tcp_check

    with patch("socket.create_connection", side_effect=OSError("refused")):
        ok, message = _tcp_check("192.168.1.1", 80)

    assert ok is False
    assert "Could not reach" in message


def test_http_check_success():
    from mediainfo.outputs.config_dashboard import _http_check

    with patch("mediainfo.outputs.config_dashboard.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        ok, message = _http_check("0.0.0.0", 8090)

    assert ok is True
    assert "127.0.0.1:8090" in message  # 0.0.0.0 rewritten to loopback


def test_http_check_failure():
    from mediainfo.outputs.config_dashboard import _http_check

    with patch(
        "mediainfo.outputs.config_dashboard.requests.get", side_effect=ConnectionError("refused")
    ):
        ok, message = _http_check("127.0.0.1", 8090)

    assert ok is False
