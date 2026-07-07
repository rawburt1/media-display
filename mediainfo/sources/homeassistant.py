"""Home Assistant "now playing" source: tracks media_player entity state
via HA's WebSocket API (a persistent, push-based subscription), rather
than polling a single entity's REST state every tick.

Useful as a fallback for devices a more specific source can't read "now
playing" from directly - e.g. a tvOS app like SVT Play that never populates
Apple's own now-playing API, which leaves pyatv (see sources.appletv) only
ever seeing the device as idle. Home Assistant's own Apple TV integration
can still see it (apparently via a long-since-established MRP pairing this
codebase can no longer make fresh, since the device stopped advertising MRP
over mDNS at some point) - reading that entity through HA's API sidesteps
the problem entirely, at the cost of depending on HA staying up.

Not specific to Apple TV: this works for any media_player entity HA
tracks. With `entity_id` configured, only that entity is ever reported
(the original behaviour, unchanged). Left blank, every media_player
entity is tracked and the one actually playing is reported - the first
one found "playing", falling back to the first "paused" one (which
get_now_playing() then still reports as idle, same as every other source
- see _select_entity's docstring for why that fallback exists anyway) -
mirroring the same auto-select pattern used by the LMS source for
multi-player households.

Runs its own background thread (a synchronous websocket-client
WebSocketApp, not a second asyncio loop) that holds the connection and
keeps every tracked entity's latest state in memory; get_now_playing()
only ever reads that cache - there's no network call on the polling path
at all, unlike the old REST-per-poll version.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

import websocket

from mediainfo.config import HomeAssistantConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# HA media_player states that count as "actually playing" - paused/idle/off/
# standby/buffering/unavailable are all treated as "nothing playing" rather
# than an error (see MediaSource.last_poll_failed's docstring).
_PLAYING_STATES = frozenset(["playing"])

# How long to wait before reconnecting after the WebSocket connection drops
# for any reason (server restart, network blip, auth rejected, ...).
_RECONNECT_DELAY_SECONDS = 5


class HomeAssistantSource(MediaSource):
    name = "homeassistant"

    def __init__(self, config: HomeAssistantConfig):
        self.config = config
        scheme = "https" if config.use_ssl else "http"
        self._base = f"{scheme}://{config.host}:{config.port}"
        ws_scheme = "wss" if config.use_ssl else "ws"
        self._ws_url = f"{ws_scheme}://{config.host}:{config.port}/api/websocket"

        self._lock = threading.Lock()
        self._connected = False
        self._auth_failed = False
        self._msg_id = 1
        # entity_id -> {"state": str, "attributes": dict, "ts": monotonic
        # receipt time} - one entry per media_player entity HA has ever
        # reported since this connection was (re)established.
        self._entities: dict = {}

        threading.Thread(target=self._run_forever, daemon=True).start()

    # -- background connection (all of this runs on its own thread) --------

    def _run_forever(self) -> None:
        while True:
            try:
                app = websocket.WebSocketApp(
                    self._ws_url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                app.run_forever(ping_interval=20)
            except Exception:
                logger.exception("Home Assistant source: WebSocket connection error")
            with self._lock:
                self._connected = False
            time.sleep(_RECONNECT_DELAY_SECONDS)

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _on_error(self, ws: Any, error: Any) -> None:
        logger.warning("Home Assistant source: WebSocket error: %s", error)

    def _on_close(self, ws: Any, code: Any, message: Any) -> None:
        with self._lock:
            self._connected = False

    def _on_message(self, ws: Any, message: str) -> None:
        try:
            data = json.loads(message)
        except ValueError:
            return

        msg_type = data.get("type")
        if msg_type == "auth_required":
            ws.send(json.dumps({"type": "auth", "access_token": self.config.token}))
        elif msg_type == "auth_ok":
            with self._lock:
                self._connected = True
                self._auth_failed = False
            self._subscribe(ws)
        elif msg_type == "auth_invalid":
            logger.error(
                "Home Assistant source: authentication failed - check sources.homeassistant.token"
            )
            with self._lock:
                self._auth_failed = True
        elif msg_type == "event":
            self._handle_event(data)
        elif msg_type == "result":
            self._handle_result(data)

    def _subscribe(self, ws: Any) -> None:
        ws.send(json.dumps({"id": self._next_id(), "type": "subscribe_events", "event_type": "state_changed"}))
        # A one-time full snapshot, so already-playing media shows up
        # immediately rather than waiting for its next state change.
        ws.send(json.dumps({"id": self._next_id(), "type": "get_states"}))

    def _handle_event(self, data: dict) -> None:
        event = data.get("event") or {}
        if event.get("event_type") != "state_changed":
            return
        event_data = event.get("data") or {}
        self._store_entity(event_data.get("entity_id"), event_data.get("new_state"))

    def _handle_result(self, data: dict) -> None:
        result = data.get("result")
        if not isinstance(result, list):
            return
        for entity in result:
            self._store_entity(entity.get("entity_id"), entity)

    def _store_entity(self, entity_id: Optional[str], state_obj: Optional[dict]) -> None:
        if not entity_id or not entity_id.startswith("media_player.") or not state_obj:
            return
        with self._lock:
            self._entities[entity_id] = {
                "state": state_obj.get("state"),
                "attributes": state_obj.get("attributes") or {},
                "ts": time.monotonic(),
            }

    # -- polling side (reads only the cache built up above) ----------------

    def get_now_playing(self) -> Optional[NowPlaying]:
        with self._lock:
            connected, auth_failed = self._connected, self._auth_failed
        self.last_poll_failed = not connected or auth_failed
        if self.last_poll_failed:
            return None

        entity = self._select_entity()
        if entity is None or entity["state"] not in _PLAYING_STATES:
            return None
        return self._parse_entity(entity["attributes"])

    def _select_entity(self) -> Optional[dict]:
        """Return the tracked entity to report on.

        With `entity_id` configured, always that one (whatever its state -
        get_now_playing() itself decides play vs. idle). Otherwise: the
        most recently updated entity currently "playing", falling back to
        the most recently updated "paused" one - which get_now_playing()
        then still treats as idle, same as every other source; picking it
        here rather than nothing is only about which entity would be
        reported *if* something else made paused count someday, mirroring
        the LMS source's identical fallback for the identical reason.
        """
        with self._lock:
            if self.config.entity_id:
                return self._entities.get(self.config.entity_id)
            entries = list(self._entities.values())

        playing = [e for e in entries if e["state"] in _PLAYING_STATES]
        if playing:
            return max(playing, key=lambda e: e["ts"])
        paused = [e for e in entries if e["state"] == "paused"]
        if paused:
            return max(paused, key=lambda e: e["ts"])
        return None

    def _parse_entity(self, attrs: dict) -> NowPlaying:
        images = []
        picture = attrs.get("entity_picture")
        if picture:
            images.append(Artwork(url=f"{self._base}{picture}", label="Artwork (Home Assistant)"))

        content_type = (attrs.get("media_content_type") or "").lower()
        series_title = attrs.get("media_series_title")

        if series_title or content_type in ("tvshow", "episode"):
            season = attrs.get("media_season")
            episode = attrs.get("media_episode")
            ep_title = attrs.get("media_title", "") or ""
            if season is not None and episode is not None:
                subtitle = f"S{int(season):02d}E{int(episode):02d} - {ep_title}"
            else:
                subtitle = ep_title
            return NowPlaying(
                source=self.name,
                media_type="episode",
                title=series_title or attrs.get("media_title", ""),
                subtitle=subtitle,
                images=images,
                season=int(season) if season is not None else None,
            )

        if content_type == "music" or attrs.get("media_artist"):
            return NowPlaying(
                source=self.name,
                media_type="music",
                title=attrs.get("media_title", "") or "",
                subtitle=attrs.get("media_artist", "") or "",
                album=attrs.get("media_album_name", "") or "",
                images=images,
            )

        return NowPlaying(
            source=self.name,
            media_type="movie",
            title=attrs.get("media_title", "") or attrs.get("app_name", "") or "",
            subtitle=attrs.get("app_name", "") or "",
            images=images,
        )
