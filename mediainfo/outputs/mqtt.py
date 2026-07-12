"""MQTT publish output: publishes now-playing metadata to an MQTT broker,
and (optionally) exposes a richer Home Assistant integration via MQTT
Discovery plus a couple of command topics HA can use to control this
process - not just read from it.

Publishes a JSON payload to a configurable topic whenever the playing item
changes.  Useful for triggering home-automation flows (Home Assistant, Node-RED,
etc.) or feeding data to other displays.

Payload when playing:
    {"state": "playing", "source": "kodi", "media_type": "music",
     "title": "...", "subtitle": "...", "album": "..."}

Payload when idle:
    {"state": "idle"}

With `ha_discovery: true`, retained Home Assistant MQTT discovery configs
are also published on every (re)connect, describing a "mediainfo" device
with:
  - sensors: now_playing (state + the full payload as attributes), title,
    artist (NowPlaying.subtitle - see its docstring for why that's the
    artist field for music), album, source
  - a "Health problem" binary_sensor, republished periodically (see
    on_schedule_tick) from whatever set_health_provider() was given -
    "problem" if any active source/output/enricher reports status "error"
  - a "Hitster-safe mode" switch, wired to Orchestrator.get_hitster_safe/
    set_hitster_safe via set_hitster_safe_handlers() - HA can read *and*
    toggle it
  - a "Refresh artwork" button, wired to
    Orchestrator.request_artwork_refresh via set_refresh_artwork_handler()
  - a "Next image" button, wired to Orchestrator.request_rotation_now via
    set_rotate_now_handler() - immediately advances every output's
    rotation instead of waiting for rotation_interval_seconds
  - a "Restart" button - sends this process itself SIGTERM (the same
    mechanism the config UI's own Restart button uses), so a process
    supervisor (docker-compose's `restart: unless-stopped`, etc.) brings
    it back up; needs no orchestrator wiring since restarting the whole
    process doesn't touch orchestrator state

There's no separate "idle mode" entity - the now_playing sensor's own
"idle" state already covers that (see roadmap discussion; this was a
deliberate scope decision, not an oversight).

An availability topic (<topic>/availability, with a last-will) makes the
entities show "unavailable" when this process goes away.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import time
from pathlib import Path
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from mediainfo.app_services import AppServices
from mediainfo.cache import ImageCache
from mediainfo.config import MqttConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.outputs.base import Output

logger = logging.getLogger(__name__)

# There's no "health changed" or "hitster-safe changed some other way"
# event to hook for republishing their MQTT state, so on_schedule_tick()
# just caps how often it re-publishes them to this interval.
_STATE_REPUBLISH_INTERVAL_SECONDS = 60


class MqttOutput(Output):
    handles_images = False

    def __init__(self, config: MqttConfig):
        self.config = config
        self._client = mqtt.Client(client_id=config.client_id)
        if config.username:
            self._client.username_pw_set(config.username, config.password)
        self._client.on_disconnect = self._on_disconnect
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        if config.ha_discovery:
            # Last-will: the broker marks us unavailable if this process
            # dies without a clean disconnect, so HA entities go
            # "unavailable" instead of freezing on the last state.
            self._client.will_set(
                self._availability_topic, "offline", qos=config.qos, retain=True
            )
        self._health_fn: Optional[Callable[[], dict]] = None
        self._hitster_safe_get: Optional[Callable[[], bool]] = None
        self._hitster_safe_set: Optional[Callable[[bool], None]] = None
        self._refresh_artwork_fn: Optional[Callable[[], None]] = None
        self._rotate_now_fn: Optional[Callable[[], None]] = None
        self._last_state_republish: Optional[float] = None
        try:
            self._client.connect_async(config.host, config.port, keepalive=60)
        except Exception:
            logger.warning(
                "MQTT: could not initiate connection to %s:%s", config.host, config.port
            )
        self._client.loop_start()

    # -- cross-cutting wiring (see wiring.py) ------------------------------

    def set_health_provider(self, fn: Optional[Callable[[], dict]]) -> None:
        """Register a callable returning the health JSON dict - published
        as a "problem" binary_sensor when ha_discovery is enabled (see
        on_schedule_tick/_publish_health_state)."""
        self._health_fn = fn

    def set_hitster_safe_handlers(
        self,
        get_fn: Optional[Callable[[], bool]],
        set_fn: Optional[Callable[[bool], None]],
    ) -> None:
        """Register the orchestrator's Hitster-safe get/set, so an HA
        "switch" entity can read and toggle it (see _on_message)."""
        self._hitster_safe_get = get_fn
        self._hitster_safe_set = set_fn

    def set_refresh_artwork_handler(self, fn: Optional[Callable[[], None]]) -> None:
        """Register a callable (Orchestrator.request_artwork_refresh) an
        HA "button" entity triggers (see _on_message)."""
        self._refresh_artwork_fn = fn

    def set_rotate_now_handler(self, fn: Optional[Callable[[], None]]) -> None:
        """Register a callable (Orchestrator.request_rotation_now) an HA
        "button" entity triggers (see _on_message)."""
        self._rotate_now_fn = fn

    def attach(self, services: AppServices) -> None:
        self.set_health_provider(services.health_provider)
        self.set_hitster_safe_handlers(
            services.get_hitster_safe, services.set_hitster_safe
        )
        self.set_refresh_artwork_handler(services.request_artwork_refresh)
        self.set_rotate_now_handler(services.request_rotation_now)

    @property
    def _availability_topic(self) -> str:
        return f"{self.config.topic}/availability"

    @property
    def _hitster_safe_command_topic(self) -> str:
        return f"{self.config.topic}/hitster_safe/set"

    @property
    def _hitster_safe_state_topic(self) -> str:
        return f"{self.config.topic}/hitster_safe/state"

    @property
    def _refresh_artwork_command_topic(self) -> str:
        return f"{self.config.topic}/refresh_artwork/set"

    @property
    def _rotate_now_command_topic(self) -> str:
        return f"{self.config.topic}/next_image/set"

    @property
    def _restart_command_topic(self) -> str:
        return f"{self.config.topic}/restart/set"

    @property
    def _health_state_topic(self) -> str:
        return f"{self.config.topic}/health/state"

    def update(
        self, now_playing: NowPlaying, artwork: Artwork, image_path: Path
    ) -> None:
        pass

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        self._publish(
            {
                "state": "playing",
                "source": now_playing.source,
                "media_type": now_playing.media_type,
                "title": now_playing.title,
                "subtitle": now_playing.subtitle,
                "album": now_playing.album,
            }
        )

    def on_idle(self) -> None:
        self._publish({"state": "idle"})

    def health_check(self) -> Optional[dict]:
        return {"broker_connected": self._client.is_connected()}

    def on_schedule_tick(self) -> None:
        """Periodically republish the health/hitster-safe entity states,
        so they're current even if nothing has *changed* them recently -
        e.g. right after an HA restart re-subscribes. Throttled to
        _STATE_REPUBLISH_INTERVAL_SECONDS since this is called every poll
        tick and neither value has a "just changed" event to hook here.
        """
        if not self.config.ha_discovery:
            return
        now = time.monotonic()
        if (
            self._last_state_republish is not None
            and now - self._last_state_republish < _STATE_REPUBLISH_INTERVAL_SECONDS
        ):
            return
        self._last_state_republish = now
        self._publish_health_state()
        self._publish_hitster_safe_state()

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

    def _publish_health_state(self) -> None:
        if self._health_fn is None:
            return
        try:
            data = self._health_fn()
            problem = any(
                entry.get("status") == "error"
                for category in ("sources", "outputs", "enrichers")
                for entry in data.get(category, [])
            )
            self._client.publish(
                self._health_state_topic,
                "ON" if problem else "OFF",
                qos=self.config.qos,
                retain=True,
            )
        except Exception:
            logger.exception("MQTT: failed to publish health state")

    def _publish_hitster_safe_state(self) -> None:
        if self._hitster_safe_get is None:
            return
        try:
            enabled = self._hitster_safe_get()
            self._client.publish(
                self._hitster_safe_state_topic,
                "ON" if enabled else "OFF",
                qos=self.config.qos,
                retain=True,
            )
        except Exception:
            logger.exception("MQTT: failed to publish hitster-safe state")

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
            # Subscriptions never persist across a reconnect regardless
            # (unlike retained messages), so those are redone here too.
            self._publish_ha_discovery()
            self._subscribe_commands()
            self._publish_health_state()
            self._publish_hitster_safe_state()

    def _subscribe_commands(self) -> None:
        try:
            self._client.subscribe(
                self._hitster_safe_command_topic, qos=self.config.qos
            )
            self._client.subscribe(
                self._refresh_artwork_command_topic, qos=self.config.qos
            )
            self._client.subscribe(self._rotate_now_command_topic, qos=self.config.qos)
            self._client.subscribe(self._restart_command_topic, qos=self.config.qos)
        except Exception:
            logger.exception("MQTT: failed to subscribe to command topics")

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = msg.payload.decode("utf-8", errors="replace").strip()
        except Exception:
            logger.exception("MQTT: failed to decode incoming message on %s", msg.topic)
            return

        if msg.topic == self._hitster_safe_command_topic:
            if self._hitster_safe_set is None:
                return
            self._hitster_safe_set(payload.upper() == "ON")
            self._publish_hitster_safe_state()
        elif msg.topic == self._refresh_artwork_command_topic:
            if self._refresh_artwork_fn is not None:
                self._refresh_artwork_fn()
        elif msg.topic == self._rotate_now_command_topic:
            if self._rotate_now_fn is not None:
                self._rotate_now_fn()
        elif msg.topic == self._restart_command_topic:
            logger.info("Restarting (SIGTERM to self) - requested via MQTT")
            os.kill(os.getpid(), signal.SIGTERM)
        else:
            logger.debug("MQTT: ignoring message on unrecognized topic %s", msg.topic)

    def _publish_ha_discovery(self) -> None:
        """Publish retained HA discovery configs for a "mediainfo" device:
        five sensors reading the existing state topic (now_playing, title,
        artist, album, source), a health problem binary_sensor, a
        hitster-safe switch, and a refresh-artwork button - see the module
        docstring for what each does.
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
            "artist": {
                "name": "Artist",
                "unique_id": f"{node}_artist",
                "state_topic": self.config.topic,
                # subtitle holds the artist for music items - see
                # NowPlaying.subtitle's docstring. Blank for other media.
                "value_template": "{{ value_json.subtitle | default('') }}",
                "icon": "mdi:account-music",
            },
            "album": {
                "name": "Album",
                "unique_id": f"{node}_album",
                "state_topic": self.config.topic,
                "value_template": "{{ value_json.album | default('') }}",
                "icon": "mdi:album",
            },
            "source": {
                "name": "Source",
                "unique_id": f"{node}_source",
                "state_topic": self.config.topic,
                "value_template": "{{ value_json.source | default('') }}",
                "icon": "mdi:remote-tv",
            },
        }
        for object_id, payload in sensors.items():
            self._publish_discovery_entity("sensor", node, object_id, device, payload)

        binary_sensors: dict[str, dict] = {
            "health": {
                "name": "Health problem",
                "unique_id": f"{node}_health",
                "state_topic": self._health_state_topic,
                "device_class": "problem",
                "icon": "mdi:heart-pulse",
            },
        }
        for object_id, payload in binary_sensors.items():
            self._publish_discovery_entity(
                "binary_sensor", node, object_id, device, payload
            )

        switches: dict[str, dict] = {
            "hitster_safe": {
                "name": "Hitster-safe mode",
                "unique_id": f"{node}_hitster_safe",
                "state_topic": self._hitster_safe_state_topic,
                "command_topic": self._hitster_safe_command_topic,
                "icon": "mdi:incognito",
            },
        }
        for object_id, payload in switches.items():
            self._publish_discovery_entity("switch", node, object_id, device, payload)

        buttons: dict[str, dict] = {
            "refresh_artwork": {
                "name": "Refresh artwork",
                "unique_id": f"{node}_refresh_artwork",
                "command_topic": self._refresh_artwork_command_topic,
                "icon": "mdi:image-refresh-outline",
            },
            "next_image": {
                "name": "Next image",
                "unique_id": f"{node}_next_image",
                "command_topic": self._rotate_now_command_topic,
                "icon": "mdi:skip-next-outline",
            },
            "restart": {
                "name": "Restart",
                "unique_id": f"{node}_restart",
                "command_topic": self._restart_command_topic,
                "device_class": "restart",
                "icon": "mdi:restart",
            },
        }
        for object_id, payload in buttons.items():
            self._publish_discovery_entity("button", node, object_id, device, payload)

        try:
            self._client.publish(
                self._availability_topic, "online", qos=self.config.qos, retain=True
            )
        except Exception:
            logger.exception("MQTT: failed to publish availability")

    def _publish_discovery_entity(
        self, component: str, node: str, object_id: str, device: dict, payload: dict
    ) -> None:
        entry = dict(payload)
        entry["availability_topic"] = self._availability_topic
        entry["device"] = device
        topic = (
            f"{self.config.ha_discovery_prefix}/{component}/{node}/{object_id}/config"
        )
        try:
            # retain=True regardless of config.retain: an unretained
            # discovery config disappears for any HA that (re)starts
            # after we published it, which defeats the point.
            self._client.publish(
                topic, json.dumps(entry), qos=self.config.qos, retain=True
            )
        except Exception:
            logger.exception(
                "MQTT: failed to publish HA discovery config for %s", object_id
            )
