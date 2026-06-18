"""Apple TV "now playing" source, via pyatv.

Connects to an Apple TV device over the local network and polls the
currently-playing media item: title, artist, album, and artwork.

Pairing is required before first use (tvOS 15+: Companion protocol):

  python -m mediainfo auth appletv --config config.yaml

The above command scans for the device, prompts for the PIN shown on-screen,
and prints the credentials to paste into config.yaml.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import tempfile
import threading
from pathlib import Path
from typing import Optional

import pyatv

from mediainfo.config import AppleTvConfig
from mediainfo.models import Artwork, NowPlaying
from mediainfo.sources.base import MediaSource

logger = logging.getLogger(__name__)

# DeviceState.name values that count as "playing".
_PLAYING_STATES = frozenset(["playing", "loading"])

# Artwork is written here keyed by SHA-256 of its bytes so different art
# produces different filenames (cache invalidation) while identical art
# reuses the existing file.
_ART_DIR = Path(tempfile.gettempdir()) / "pixoo-appletv-art"


def _enum_name(value: object) -> str:
    """Return the lowercase .name of a pyatv enum value, robustly."""
    return getattr(value, "name", str(value)).lower()


def _map_media_type(media_type: object) -> str:
    name = _enum_name(media_type)
    if name == "music":
        return "music"
    if name in ("tv", "tvshow"):
        return "episode"
    return "movie"  # Video / Unknown


class AppleTvSource(MediaSource):
    name = "appletv"

    def __init__(self, config: AppleTvConfig):
        self._config = config
        self._atv = None
        self._loop = asyncio.new_event_loop()
        _ART_DIR.mkdir(exist_ok=True)
        threading.Thread(
            target=self._loop.run_forever, daemon=True, name="pyatv-loop"
        ).start()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_now_playing(self) -> Optional[NowPlaying]:
        future = asyncio.run_coroutine_threadsafe(self._fetch(), self._loop)
        try:
            return future.result(timeout=15)
        except Exception:
            logger.exception("Apple TV source error")
            return None

    # ------------------------------------------------------------------
    # Async internals (all run on self._loop)
    # ------------------------------------------------------------------

    async def _fetch(self) -> Optional[NowPlaying]:
        if self._atv is None:
            await self._connect()
        if self._atv is None:
            return None

        try:
            playing = await self._atv.metadata.playing()
        except Exception:
            logger.warning("Apple TV: connection lost; will reconnect next poll")
            await self._disconnect()
            return None

        if _enum_name(playing.device_state) not in _PLAYING_STATES:
            return None

        title = playing.title or ""
        if not title:
            return None

        images = []
        art_path = await self._fetch_artwork()
        if art_path is not None:
            images.append(Artwork(url=art_path.as_uri(), label="Apple TV artwork"))

        return NowPlaying(
            source=self.name,
            media_type=_map_media_type(playing.media_type),
            title=title,
            subtitle=playing.artist or "",
            album=playing.album or "",
            images=images,
        )

    async def _fetch_artwork(self) -> Optional[Path]:
        try:
            art = await self._atv.metadata.artwork(width=600, height=600)
            if art is None or not art.bytes:
                return None
            digest = hashlib.sha256(art.bytes).hexdigest()[:16]
            path = _ART_DIR / f"appletv_{digest}.jpg"
            if not path.exists():
                path.write_bytes(art.bytes)
            return path
        except Exception:
            logger.debug("Apple TV: could not fetch artwork")
            return None

    async def _connect(self) -> None:
        try:
            results = await pyatv.scan(hosts=[self._config.host])
            if not results:
                logger.warning("Apple TV: no device found at %s", self._config.host)
                return

            conf = results[0]
            _apply_credentials(conf, self._config)
            self._atv = await pyatv.connect(conf)
            logger.info("Apple TV: connected to %s", conf.name)
        except Exception:
            logger.exception("Apple TV: failed to connect to %s", self._config.host)

    async def _disconnect(self) -> None:
        if self._atv is not None:
            try:
                self._atv.close()
            except Exception:
                pass
            self._atv = None


def _apply_credentials(conf, config: AppleTvConfig) -> None:
    """Apply any configured credentials to a pyatv AppleTV config object."""
    pairs = [
        (pyatv.Protocol.Companion, config.companion_credentials),
        (pyatv.Protocol.MRP, config.mrp_credentials),
        (pyatv.Protocol.AirPlay, config.airplay_credentials),
    ]
    for protocol, creds in pairs:
        if creds:
            conf.set_credentials(protocol, creds)
