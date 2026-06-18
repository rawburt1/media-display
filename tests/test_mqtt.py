"""Tests for the MQTT publish output."""

import json
from unittest.mock import MagicMock, patch

import pytest

from mediainfo.config import MqttConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.mqtt import MqttOutput


def _config(**kwargs):
    defaults = dict(
        enabled=True,
        host="localhost",
        port=1883,
        topic="mediainfo/now_playing",
        client_id="test-client",
        username="",
        password="",
        qos=0,
        retain=True,
    )
    defaults.update(kwargs)
    return MqttConfig(**defaults)


def _now_playing(**kwargs):
    defaults = dict(
        source="kodi",
        media_type="music",
        title="Bohemian Rhapsody",
        subtitle="Queen",
        album="A Night at the Opera",
        images=[],
    )
    defaults.update(kwargs)
    return NowPlaying(**defaults)


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_publishes_playing_payload_on_new_item(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config())

    output.on_new_item(_now_playing(), MagicMock())

    mock_client.publish.assert_called_once()
    args, kwargs = mock_client.publish.call_args
    assert args[0] == "mediainfo/now_playing"
    payload = json.loads(args[1])
    assert payload["state"] == "playing"
    assert payload["title"] == "Bohemian Rhapsody"
    assert payload["subtitle"] == "Queen"
    assert payload["album"] == "A Night at the Opera"
    assert payload["source"] == "kodi"
    assert payload["media_type"] == "music"


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_publishes_idle_payload_on_idle(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config())

    output.on_idle()

    mock_client.publish.assert_called_once()
    args, _ = mock_client.publish.call_args
    payload = json.loads(args[1])
    assert payload == {"state": "idle"}


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_publishes_to_configured_topic(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(topic="home/living_room/media"))

    output.on_new_item(_now_playing(), MagicMock())

    args, _ = mock_client.publish.call_args
    assert args[0] == "home/living_room/media"


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_retain_and_qos_passed_to_publish(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(qos=1, retain=False))

    output.on_idle()

    _, kwargs = mock_client.publish.call_args
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is False


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_credentials_set_when_username_provided(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(username="user", password="secret"))

    mock_client.username_pw_set.assert_called_once_with("user", "secret")


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_no_credentials_when_username_blank(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(username="", password=""))

    mock_client.username_pw_set.assert_not_called()


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_loop_start_called_on_init(MockClient):
    mock_client = MockClient.return_value
    MqttOutput(_config())

    mock_client.loop_start.assert_called_once()


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_update_is_noop(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config())
    mock_client.publish.reset_mock()

    output.update(_now_playing(), Artwork(url="https://example.com/a.jpg"), "/tmp/a.jpg")

    mock_client.publish.assert_not_called()


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_publish_exception_does_not_propagate(MockClient):
    mock_client = MockClient.return_value
    mock_client.publish.side_effect = RuntimeError("broker gone")
    output = MqttOutput(_config())

    # Should not raise
    output.on_idle()
    output.on_new_item(_now_playing(), MagicMock())


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_connect_failure_does_not_prevent_loop_start(MockClient):
    mock_client = MockClient.return_value
    mock_client.connect_async.side_effect = OSError("connection refused")

    output = MqttOutput(_config())

    mock_client.loop_start.assert_called_once()
