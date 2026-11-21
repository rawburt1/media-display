"""Current weather from a Home Assistant weather entity - used by the
weather word clock (/ordklocka/vader, see outputs.web.weather_entity).

Reuses the Home Assistant source's host and token (sources.homeassistant),
so no new service or key is involved. Results are cached, failures are
logged once and retried later, and nothing here ever raises.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

import requests

from mediainfo.config import HomeAssistantConfig

logger = logging.getLogger(__name__)

# Only plain weather entity ids reach the URL path.
_ENTITY_RE = re.compile(r"^weather\.[a-z0-9_]+$")

Weather = Dict[str, Any]


class HomeAssistantWeather:
    """Reads /api/states/<weather entity> and keeps the answer for a while."""

    # Weather changes slowly; a failed lookup is retried sooner.
    TTL_SECONDS = 600.0
    RETRY_SECONDS = 120.0
    TIMEOUT_SECONDS = 5.0

    def __init__(
        self,
        config: HomeAssistantConfig,
        get: Callable[..., Any] = requests.get,
        clock: Callable[[], float] = time.monotonic,
    ):
        scheme = "https" if config.use_ssl else "http"
        self._base = f"{scheme}://{config.host}:{config.port}/api/states/"
        self._token = config.token
        self._get = get
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: Dict[str, Tuple[float, Optional[Weather]]] = {}
        self._failing: set[str] = set()

    def current(self, entity_id: str) -> Optional[Weather]:
        """{"condition": "rainy", "temperature": 7.5, "unit": "°C"} or None."""
        if not _ENTITY_RE.match(entity_id or ""):
            return None
        now = self._clock()
        with self._lock:
            cached = self._cache.get(entity_id)
            if cached and cached[0] > now:
                return cached[1]
        weather = self._fetch(entity_id)
        ttl = self.TTL_SECONDS if weather else self.RETRY_SECONDS
        with self._lock:
            self._cache[entity_id] = (now + ttl, weather)
        return weather

    def _fetch(self, entity_id: str) -> Optional[Weather]:
        try:
            resp = self._get(
                self._base + entity_id,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=self.TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            state = resp.json()
            attributes = state.get("attributes") or {}
            temperature = attributes.get("temperature")
            weather: Weather = {
                "condition": str(state.get("state") or ""),
                "temperature": float(temperature) if temperature is not None else None,
                "unit": str(attributes.get("temperature_unit") or "°C"),
            }
        except Exception as exc:  # network, HTTP, JSON or value errors
            if entity_id not in self._failing:
                # No URL or headers in the message - the token stays out of logs.
                logger.warning(
                    "Could not read the weather from Home Assistant (%s): %s",
                    entity_id,
                    type(exc).__name__,
                )
            self._failing.add(entity_id)
            return None
        if weather["condition"] in ("", "unavailable", "unknown"):
            return None
        self._failing.discard(entity_id)
        return weather


def make_weather_provider(sources: Dict[str, Any]) -> Optional[Callable[[str], Optional[Weather]]]:
    """HomeAssistantWeather(...).current when the Home Assistant source is
    enabled and has a host and token, else None (no weather)."""
    ha = sources.get("homeassistant")
    if not isinstance(ha, HomeAssistantConfig) or not (ha.enabled and ha.host and ha.token):
        return None
    return HomeAssistantWeather(ha).current
