"""MQTT publish output: publishes now-playing metadata to an MQTT broker.

Publishes a JSON payload to a configurable topic whenever the playing item
changes.  Useful for triggering home-automation flows (Home Assistant, Node-RED,
etc.) or feeding data to other displays.

Payload when playing:
    {"state": "playing", "source": "kodi", "media_type": "music",
     "title": "...", "subtitle": "...", "album": "..."}

Payload when idle:
    {"state": "idle"}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import paho.mqtt.client as mqtt

from pixoo_media.cache import ImageCache
from pixoo_media.config import MqttConfig
from pixoo_media.models import Artwork, NowPlaying
from pixoo_media.outputs.base import Output

logger = logging.getLogger(__name__)


class MqttOutput(Output):
    handles_images = False

    def __init__(self, config: MqttConfig):
        self.config = config
        self._client = mqtt.Client(client_id=config.client_id)
        if config.username:
            self._client.username_pw_set(config.username, config.password)
        self._client.on_disconnect = self._on_disconnect
        try:
            self._client.connect_async(config.host, config.port, keepalive=60)
        except Exception:
            logger.warning("MQTT: could not initiate connection to %s:%s", config.host, config.port)
        self._client.loop_start()

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
