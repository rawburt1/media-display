"""Tests for the dashboard UI's test-connection logic.

Per-plugin test_connection() behavior (thetvdb, fanarttv, discogs, lastfm,
musicbrainz, wikipedia, tmdb, omdb, library, sonarr/radarr/lidarr, every
source via MediaSource's shared implementation, AppleTvSource's override)
now lives in each plugin's own test file - see mediainfo/sources/base.py
and mediainfo/enrichers/base.py's test_connection() docstrings. This file
only covers the generic registry-driven dispatch in test_source()/
test_enricher() themselves, plus test_output() (which stays a raw field-
based check here - see config_dashboard.py's module docstring for why).
"""

from unittest.mock import MagicMock, patch

from mediainfo.outputs.config_dashboard import (
    test_enricher as check_enricher,
    test_output as check_output,
    test_source as check_source,
)

# ---------------------------------------------------------------------------
# test_source
# ---------------------------------------------------------------------------


class _FakeSource:
    def __init__(self, config):
        self.config = config

    def test_connection(self):
        return True, "fake source connected"


def test_source_unknown_name_returns_false():
    ok, message = check_source("nonexistent", MagicMock())
    assert ok is False
    assert "Unknown" in message


def test_source_none_config_returns_false():
    with patch("mediainfo.registries.SOURCE_CLASSES", {"fake": _FakeSource}):
        ok, message = check_source("fake", None)
    assert ok is False


def test_source_delegates_to_test_connection():
    with patch("mediainfo.registries.SOURCE_CLASSES", {"fake": _FakeSource}):
        ok, message = check_source("fake", MagicMock())

    assert ok is True
    assert message == "fake source connected"


def test_source_construction_exception_is_caught():
    class _Source(_FakeSource):
        def __init__(self, config):
            raise RuntimeError("boom")

    with patch("mediainfo.registries.SOURCE_CLASSES", {"fake": _Source}):
        ok, message = check_source("fake", MagicMock())

    assert ok is False
    assert "boom" in message


# ---------------------------------------------------------------------------
# test_enricher
# ---------------------------------------------------------------------------


class _FakeEnricher:
    def __init__(self, config):
        self.config = config

    def test_connection(self):
        return True, "fake enricher connected"


def test_enricher_none_config_returns_false():
    ok, message = check_enricher("thetvdb", None)
    assert ok is False
    assert "Unknown" in message


def test_enricher_unknown_name_returns_false():
    ok, message = check_enricher("nonexistent", MagicMock())
    assert ok is False


def test_enricher_delegates_to_test_connection():
    with patch("mediainfo.registries.ENRICHER_CLASSES", {"fake": _FakeEnricher}):
        ok, message = check_enricher("fake", MagicMock())

    assert ok is True
    assert message == "fake enricher connected"


def test_enricher_construction_exception_is_caught():
    class _Enricher(_FakeEnricher):
        def __init__(self, config):
            raise RuntimeError("boom")

    with patch("mediainfo.registries.ENRICHER_CLASSES", {"fake": _Enricher}):
        ok, message = check_enricher("fake", MagicMock())

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
