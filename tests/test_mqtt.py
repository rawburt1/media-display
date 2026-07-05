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
    MqttOutput(_config(username="user", password="secret"))

    mock_client.username_pw_set.assert_called_once_with("user", "secret")


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_no_credentials_when_username_blank(MockClient):
    mock_client = MockClient.return_value
    MqttOutput(_config(username="", password=""))

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

    MqttOutput(_config())

    mock_client.loop_start.assert_called_once()


# ---------------------------------------------------------------------------
# Home Assistant MQTT discovery (ha_discovery: true)
# ---------------------------------------------------------------------------

@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_discovery_off_by_default(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config())

    mock_client.will_set.assert_not_called()
    output._on_connect(mock_client, None, {}, 0)
    mock_client.publish.assert_not_called()


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_discovery_sets_last_will_on_availability_topic(MockClient):
    mock_client = MockClient.return_value
    MqttOutput(_config(ha_discovery=True))

    mock_client.will_set.assert_called_once_with(
        "mediainfo/now_playing/availability", "offline", qos=0, retain=True
    )


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_discovery_publishes_retained_sensor_configs_on_connect(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    output._on_connect(mock_client, None, {}, 0)

    published = {call.args[0]: call for call in mock_client.publish.call_args_list}
    config_topic = "homeassistant/sensor/test-client/now_playing/config"
    assert config_topic in published
    call = published[config_topic]
    assert call.kwargs["retain"] is True
    payload = json.loads(call.args[1])
    assert payload["state_topic"] == "mediainfo/now_playing"
    assert payload["value_template"] == "{{ value_json.state }}"
    assert payload["json_attributes_topic"] == "mediainfo/now_playing"
    assert payload["availability_topic"] == "mediainfo/now_playing/availability"
    assert payload["unique_id"] == "test-client_now_playing"
    assert payload["device"]["identifiers"] == ["test-client"]

    title_payload = json.loads(
        published["homeassistant/sensor/test-client/title/config"].args[1]
    )
    assert title_payload["unique_id"] == "test-client_title"
    assert "value_json.title" in title_payload["value_template"]

    # Availability flips online (retained) after the configs.
    online = published["mediainfo/now_playing/availability"]
    assert online.args[1] == "online"
    assert online.kwargs["retain"] is True


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_discovery_respects_custom_prefix_and_sanitizes_client_id(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(
        _config(ha_discovery=True, ha_discovery_prefix="ha/disc", client_id="my client!")
    )

    output._on_connect(mock_client, None, {}, 0)

    topics = [call.args[0] for call in mock_client.publish.call_args_list]
    assert "ha/disc/sensor/my_client_/now_playing/config" in topics


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_discovery_not_published_on_failed_connect(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    output._on_connect(mock_client, None, {}, 5)  # rc != 0: refused

    mock_client.publish.assert_not_called()


# ---------------------------------------------------------------------------
# MqttConfig validation (pydantic dataclass spike - see mediainfo/config/
# outputs.py's MqttConfig docstring)
# ---------------------------------------------------------------------------

def test_port_out_of_range_raises_validation_error():
    with pytest.raises(ValueError, match="port"):
        _config(port=99999)


def test_qos_out_of_range_raises_validation_error():
    with pytest.raises(ValueError, match="qos"):
        _config(qos=5)


def test_boundary_values_are_accepted():
    cfg = _config(port=65535, qos=2)
    assert cfg.port == 65535
    assert cfg.qos == 2


def test_unknown_field_raises_validation_error():
    with pytest.raises(ValueError, match="no_such_field"):
        _config(no_such_field="x")


def test_schema_reports_plain_int_defaults_not_field_info():
    from mediainfo.config import MqttConfig
    from mediainfo.outputs.config_schema import _scalar_fields

    fields = {f["name"]: f for f in _scalar_fields(MqttConfig, "outputs", "mqtt")}
    assert fields["port"]["default"] == 1883
    assert isinstance(fields["port"]["default"], int)
    assert fields["qos"]["default"] == 0
    assert isinstance(fields["qos"]["default"], int)
