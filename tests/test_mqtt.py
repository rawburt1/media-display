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

    title_payload = json.loads(published["homeassistant/sensor/test-client/title/config"].args[1])
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


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_discovery_publishes_artist_album_source_sensors(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    output._on_connect(mock_client, None, {}, 0)

    published = {call.args[0]: call for call in mock_client.publish.call_args_list}
    artist = json.loads(published["homeassistant/sensor/test-client/artist/config"].args[1])
    assert "value_json.subtitle" in artist["value_template"]
    album = json.loads(published["homeassistant/sensor/test-client/album/config"].args[1])
    assert "value_json.album" in album["value_template"]
    source = json.loads(published["homeassistant/sensor/test-client/source/config"].args[1])
    assert "value_json.source" in source["value_template"]


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_discovery_publishes_health_binary_sensor(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    output._on_connect(mock_client, None, {}, 0)

    published = {call.args[0]: call for call in mock_client.publish.call_args_list}
    config_topic = "homeassistant/binary_sensor/test-client/health/config"
    assert config_topic in published
    payload = json.loads(published[config_topic].args[1])
    assert payload["device_class"] == "problem"
    assert payload["state_topic"] == "mediainfo/now_playing/health/state"


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_discovery_publishes_hitster_safe_switch(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    output._on_connect(mock_client, None, {}, 0)

    published = {call.args[0]: call for call in mock_client.publish.call_args_list}
    config_topic = "homeassistant/switch/test-client/hitster_safe/config"
    assert config_topic in published
    payload = json.loads(published[config_topic].args[1])
    assert payload["command_topic"] == "mediainfo/now_playing/hitster_safe/set"
    assert payload["state_topic"] == "mediainfo/now_playing/hitster_safe/state"


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_discovery_publishes_refresh_artwork_button(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    output._on_connect(mock_client, None, {}, 0)

    published = {call.args[0]: call for call in mock_client.publish.call_args_list}
    config_topic = "homeassistant/button/test-client/refresh_artwork/config"
    assert config_topic in published
    payload = json.loads(published[config_topic].args[1])
    assert payload["command_topic"] == "mediainfo/now_playing/refresh_artwork/set"


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_discovery_publishes_next_image_button(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    output._on_connect(mock_client, None, {}, 0)

    published = {call.args[0]: call for call in mock_client.publish.call_args_list}
    config_topic = "homeassistant/button/test-client/next_image/config"
    assert config_topic in published
    payload = json.loads(published[config_topic].args[1])
    assert payload["command_topic"] == "mediainfo/now_playing/next_image/set"


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_discovery_publishes_restart_button(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    output._on_connect(mock_client, None, {}, 0)

    published = {call.args[0]: call for call in mock_client.publish.call_args_list}
    config_topic = "homeassistant/button/test-client/restart/config"
    assert config_topic in published
    payload = json.loads(published[config_topic].args[1])
    assert payload["command_topic"] == "mediainfo/now_playing/restart/set"
    assert payload["device_class"] == "restart"


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_connect_subscribes_to_command_topics_when_discovery_enabled(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    output._on_connect(mock_client, None, {}, 0)

    subscribed = {call.args[0] for call in mock_client.subscribe.call_args_list}
    assert output._hitster_safe_command_topic in subscribed
    assert output._refresh_artwork_command_topic in subscribed
    assert output._rotate_now_command_topic in subscribed
    assert output._restart_command_topic in subscribed


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_connect_does_not_subscribe_when_discovery_disabled(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config())

    output._on_connect(mock_client, None, {}, 0)

    mock_client.subscribe.assert_not_called()


# ---------------------------------------------------------------------------
# Command topics: hitster-safe switch and refresh-artwork button
# ---------------------------------------------------------------------------


def _message(topic, payload):
    msg = MagicMock()
    msg.topic = topic
    msg.payload = payload.encode("utf-8")
    return msg


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_hitster_safe_command_toggles_via_handler(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))
    set_fn = MagicMock()
    output.set_hitster_safe_handlers(MagicMock(return_value=False), set_fn)
    mock_client.publish.reset_mock()

    output._on_message(mock_client, None, _message(output._hitster_safe_command_topic, "ON"))

    set_fn.assert_called_once_with(True)
    # State is republished immediately after a command, not just on a timer.
    state_calls = [
        c
        for c in mock_client.publish.call_args_list
        if c.args[0] == output._hitster_safe_state_topic
    ]
    assert len(state_calls) == 1
    assert state_calls[0].args[1] == "OFF"  # reflects the getter, not the command


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_hitster_safe_command_off(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))
    set_fn = MagicMock()
    output.set_hitster_safe_handlers(MagicMock(return_value=True), set_fn)

    output._on_message(mock_client, None, _message(output._hitster_safe_command_topic, "OFF"))

    set_fn.assert_called_once_with(False)


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_hitster_safe_command_ignored_when_not_wired(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    # Must not raise even though set_hitster_safe_handlers was never called.
    output._on_message(mock_client, None, _message(output._hitster_safe_command_topic, "ON"))


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_refresh_artwork_command_calls_handler(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))
    refresh_fn = MagicMock()
    output.set_refresh_artwork_handler(refresh_fn)

    output._on_message(mock_client, None, _message(output._refresh_artwork_command_topic, "PRESS"))

    refresh_fn.assert_called_once_with()


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_refresh_artwork_command_ignored_when_not_wired(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    # Must not raise even though set_refresh_artwork_handler was never called.
    output._on_message(mock_client, None, _message(output._refresh_artwork_command_topic, "PRESS"))


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_rotate_now_command_calls_handler(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))
    rotate_fn = MagicMock()
    output.set_rotate_now_handler(rotate_fn)

    output._on_message(mock_client, None, _message(output._rotate_now_command_topic, "PRESS"))

    rotate_fn.assert_called_once_with()


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_rotate_now_command_ignored_when_not_wired(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    # Must not raise even though set_rotate_now_handler was never called.
    output._on_message(mock_client, None, _message(output._rotate_now_command_topic, "PRESS"))


@patch("mediainfo.outputs.mqtt.os.kill")
@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_restart_command_sends_sigterm_to_self(MockClient, mock_kill):
    import os
    import signal

    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    output._on_message(mock_client, None, _message(output._restart_command_topic, "PRESS"))

    mock_kill.assert_called_once_with(os.getpid(), signal.SIGTERM)


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_message_on_unrecognized_topic_is_ignored(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))

    # Must not raise.
    output._on_message(mock_client, None, _message("some/other/topic", "x"))


# ---------------------------------------------------------------------------
# attach() - see mediainfo.app_services.AppServices
# ---------------------------------------------------------------------------


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_attach_wires_health_hitster_safe_and_command_handlers(MockClient):
    from mediainfo.app_services import AppServices, OrchestratorCommands

    output = MqttOutput(_config(ha_discovery=True))

    def health_provider():
        return {"status": "ok"}

    set_fn = MagicMock()
    refresh_fn = MagicMock()
    rotate_fn = MagicMock()

    output.attach(
        AppServices(
            health_provider=health_provider,
            commands=OrchestratorCommands(
                get_hitster_safe=lambda: True,
                set_hitster_safe=set_fn,
                request_artwork_refresh=refresh_fn,
                request_rotation_now=rotate_fn,
            ),
        )
    )

    assert output._health_fn is health_provider
    assert output._hitster_safe_get() is True
    output._hitster_safe_set(False)
    set_fn.assert_called_once_with(False)
    assert output._refresh_artwork_fn is refresh_fn
    assert output._rotate_now_fn is rotate_fn


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_attach_with_no_commands_leaves_command_handlers_none(MockClient):
    # AppServices.commands defaults to None - attach() must degrade
    # gracefully rather than raise (see the OrchestratorCommands handle
    # this replaced four independently-defaultable AppServices fields
    # with).
    from mediainfo.app_services import AppServices

    output = MqttOutput(_config(ha_discovery=True))
    output.attach(AppServices())

    assert output._hitster_safe_get is None
    assert output._hitster_safe_set is None
    assert output._refresh_artwork_fn is None
    assert output._rotate_now_fn is None


# ---------------------------------------------------------------------------
# on_schedule_tick: periodic health/hitster-safe state republish
# ---------------------------------------------------------------------------


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_schedule_tick_noop_when_discovery_disabled(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config())
    output.set_health_provider(
        MagicMock(return_value={"sources": [], "outputs": [], "enrichers": []})
    )
    mock_client.publish.reset_mock()

    output.on_schedule_tick()

    mock_client.publish.assert_not_called()


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_schedule_tick_publishes_health_ok_when_no_errors(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))
    output.set_health_provider(
        MagicMock(
            return_value={
                "sources": [{"status": "idle"}],
                "outputs": [{"status": "ok"}],
                "enrichers": [],
            }
        )
    )
    mock_client.publish.reset_mock()

    output.on_schedule_tick()

    health_calls = [
        c for c in mock_client.publish.call_args_list if c.args[0] == output._health_state_topic
    ]
    assert len(health_calls) == 1
    assert health_calls[0].args[1] == "OFF"


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_schedule_tick_publishes_health_problem_when_an_entry_errors(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))
    output.set_health_provider(
        MagicMock(
            return_value={
                "sources": [{"status": "error"}],
                "outputs": [],
                "enrichers": [],
            }
        )
    )
    mock_client.publish.reset_mock()

    output.on_schedule_tick()

    health_calls = [
        c for c in mock_client.publish.call_args_list if c.args[0] == output._health_state_topic
    ]
    assert len(health_calls) == 1
    assert health_calls[0].args[1] == "ON"


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_schedule_tick_throttled_to_interval(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config(ha_discovery=True))
    output.set_health_provider(
        MagicMock(return_value={"sources": [], "outputs": [], "enrichers": []})
    )

    clock = iter([100.0, 100.5, 100.9])  # construction not clocked; two quick ticks
    with patch("mediainfo.outputs.mqtt.time.monotonic", lambda: next(clock)):
        mock_client.publish.reset_mock()
        output.on_schedule_tick()
        first_count = len(mock_client.publish.call_args_list)
        output.on_schedule_tick()  # well within the interval: no-op
        second_count = len(mock_client.publish.call_args_list)

    assert first_count > 0
    assert second_count == first_count


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


@patch("mediainfo.outputs.mqtt.mqtt.Client")
def test_health_check_reports_broker_connection_state(MockClient):
    mock_client = MockClient.return_value
    output = MqttOutput(_config())

    mock_client.is_connected.return_value = True
    assert output.health_check() == {"broker_connected": True}

    mock_client.is_connected.return_value = False
    assert output.health_check() == {"broker_connected": False}


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
    from mediainfo.configui.config_schema import _scalar_fields

    fields = {f["name"]: f for f in _scalar_fields(MqttConfig, "outputs", "mqtt")}
    assert fields["port"]["default"] == 1883
    assert isinstance(fields["port"]["default"], int)
    assert fields["qos"]["default"] == 0
    assert isinstance(fields["qos"]["default"], int)
