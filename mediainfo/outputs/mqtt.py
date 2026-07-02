"""MQTT publish output: publishes now-playing metadata to an MQTT broker.

Publishes a JSON payload to a configurable topic whenever the playing item
changes.  Useful for triggering home-automation flows (Home Assistant, Node-RED,
etc.) or feeding data to other displays.

Payload when playing:
    {"state": "playing", "source": "kodi", "media_type": "music",
     "title": "...", "subtitle": "...", "album": "..."}

Payload when idle:
    {"state": "idle"}

With `ha_discovery: true`, retained Home Assistant MQTT discovery configs
are also published on every (re)connect, describing two sensors (state
and title) that read the payload above via value_template - so the
now-playing state appears in HA automatically, with no change to the
payload contract and nothing to configure on the HA side. An
availability topic (<topic>/availability, with a last-will) makes the
entities show "unavailable" when this process goes away.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import paho.mqtt.client as mqtt

from mediainfo.cache import ImageCache
from mediainfo.config import MqttConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output

logger = logging.getLogger(__name__)


class MqttOutput(Output):
    handles_images = False

    def __init__(self, config: MqttConfig):
        self.config = config
        self._client = mqtt.Client(client_id=config.client_id)
        if config.username:
            self._client.username_pw_set(config.username, config.password)
        self._client.on_disconnect = self._on_disconnect
        self._client.on_connect = self._on_connect
        if config.ha_discovery:
            # Last-will: the broker marks us unavailable if this process
            # dies without a clean disconnect, so HA entities go
            # "unavailable" instead of freezing on the last state.
            self._client.will_set(
                self._availability_topic, "offline", qos=config.qos, retain=True
            )
        try:
            self._client.connect_async(config.host, config.port, keepalive=60)
        except Exception:
            logger.warning("MQTT: could not initiate connection to %s:%s", config.host, config.port)
        self._client.loop_start()

    @property
    def _availability_topic(self) -> str:
        return f"{self.config.topic}/availability"

    def update(self, now_playing: NowPlaying, artwork: Artwork, image_path: Path) -> None:
        pass

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        self._publish({
            "state": "playing",
            "source": now_playing.source,
            "media_type": now_playing.media_type,
            "title": now_playing.title,
            "subtitle": now_playing.subtitle,
            "album": now_playing.album,
        })

    def on_idle(self) -> None:
        self._publish({"state": "idle"})

    def _publish(self, payload: dict) -> None:
        try:
            self._client.publish(
                self.config.topic,
                json.dumps(payload),
                qos=self.config.qos,
                retain=self.config.retain,
            )
        except Exception:
            logger.exception("MQTT publish failed")

    def _on_disconnect(self, client, userdata, rc) -> None:
        if rc != 0:
            logger.warning("MQTT: unexpected disconnect (rc=%s); will reconnect", rc)

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc != 0:
            return
        logger.info("MQTT: connected to %s:%s", self.config.host, self.config.port)
        if self.config.ha_discovery:
            # On *every* connect, not just the first: retained configs
            # survive broker restarts, but a broker wiped of retained
            # state (or a fresh broker) gets them back this way.
            self._publish_ha_discovery()

    def _publish_ha_discovery(self) -> None:
        """Publish retained HA discovery configs for a "mediainfo" device
        with two sensors reading the existing state topic:

        - now_playing: state "playing"/"idle", with the full payload as
          entity attributes (title, subtitle, album, source, media_type).
        - title: the bare title, handy on dashboard cards without
          templating attributes.
        """
        # Discovery topic segments must be [a-zA-Z0-9_-] - sanitize the
        # client_id rather than trusting config.
        node = re.sub(r"[^A-Za-z0-9_-]", "_", self.config.client_id) or "mediainfo"
        device = {
            "identifiers": [node],
            "name": "mediainfo",
            "manufacturer": "mediainfo",
        }
        sensors: dict[str, dict] = {
            "now_playing": {
                "name": "Now playing",
                "unique_id": f"{node}_now_playing",
                "state_topic": self.config.topic,
                "value_template": "{{ value_json.state }}",
                "json_attributes_topic": self.config.topic,
                "icon": "mdi:play-circle-outline",
            },
            "title": {
                "name": "Title",
                "unique_id": f"{node}_title",
                "state_topic": self.config.topic,
                "value_template": "{{ value_json.title | default('') }}",
                "icon": "mdi:format-title",
            },
        }
        try:
            for object_id, payload in sensors.items():
                payload["availability_topic"] = self._availability_topic
                payload["device"] = device
                topic = f"{self.config.ha_discovery_prefix}/sensor/{node}/{object_id}/config"
                # retain=True regardless of config.retain: an unretained
                # discovery config disappears for any HA that (re)starts
                # after we published it, which defeats the point.
                self._client.publish(topic, json.dumps(payload), qos=self.config.qos, retain=True)
            self._client.publish(
                self._availability_topic, "online", qos=self.config.qos, retain=True
            )
        except Exception:
            logger.exception("MQTT: failed to publish HA discovery configs")
