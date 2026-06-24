"""Background loop: records short clips, detects silence, and calls a
recognition provider (AudD, ACRCloud, AcoustID, Shazam, or vibra).

If ACRCloud rate-limits us, falls back to vibra (no setup needed - it's
already built/working), then to local_folder_fallback_dir if that's
configured and vibra also has no match.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from vinyl_recognizer import acoustid, acrcloud, audd, local_folder, recorder, shazam, vibra
from vinyl_recognizer.config import RecognizerConfig

logger = logging.getLogger(__name__)


class RecognizerService:
    def __init__(self, config: RecognizerConfig):
        self.config = config
        self._device = recorder.resolve_device(config.input_device)
        self._lock = threading.Lock()
        self._current: dict = {}
        self._last_signal: float = 0.0
        self._last_recognition: float = float("-inf")
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def get_now_playing(self) -> dict:
        with self._lock:
            return dict(self._current)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("Unexpected error in recognizer loop")
            self._stop_event.wait(self.config.poll_interval_seconds)

    def tick(self) -> None:
        signal_clip = recorder.record_clip(
            self.config.signal_clip_seconds, self.config.sample_rate, self._device
        )
        level = recorder.rms(signal_clip)
        now = time.monotonic()

        if level < self.config.silence_threshold:
            if (
                self._current
                and self._last_signal
                and now - self._last_signal > self.config.silence_grace_seconds
            ):
                logger.info("Silence detected; clearing current track")
                with self._lock:
                    self._current = {}
            return

        self._last_signal = now
        if now - self._last_recognition < self.config.recognition_interval_seconds:
            return

        self._last_recognition = now
        clip = recorder.record_clip(
            self.config.recognition_clip_seconds, self.config.sample_rate, self._device
        )
        wav_bytes = recorder.to_wav_bytes(clip, self.config.sample_rate)
        result = self._recognize(wav_bytes)
        if result and result.get("title"):
            logger.info("Recognized: %s - %s", result.get("artist"), result.get("title"))
            with self._lock:
                self._current = result
        else:
            logger.info("No recognition match")

    def _recognize(self, wav_bytes: bytes) -> Optional[dict]:
        if self.config.recognition_provider == "acrcloud":
            try:
                return _tag_provider(
                    acrcloud.recognize(
                        wav_bytes,
                        self.config.acrcloud_host,
                        self.config.acrcloud_access_key,
                        self.config.acrcloud_access_secret,
                    ),
                    "acrcloud",
                )
            except acrcloud.RateLimitedError:
                logger.warning("ACRCloud is rate-limiting us; falling back to vibra")
                result = vibra.recognize(wav_bytes)
                if result:
                    return _tag_provider(result, "vibra")
                if not self.config.local_folder_fallback_dir:
                    return None
                logger.info("vibra had no match either; falling back to local_folder_fallback_dir")
                return _tag_provider(
                    local_folder.recognize(wav_bytes, self.config.local_folder_fallback_dir),
                    "local_folder",
                )
        if self.config.recognition_provider == "acoustid":
            return _tag_provider(acoustid.recognize(wav_bytes, self.config.acoustid_api_key), "acoustid")
        if self.config.recognition_provider == "shazam":
            return _tag_provider(shazam.recognize(wav_bytes), "shazam")
        if self.config.recognition_provider == "vibra":
            return _tag_provider(vibra.recognize(wav_bytes), "vibra")
        return _tag_provider(audd.recognize(wav_bytes, self.config.audd_api_key), "audd")


def _tag_provider(result: Optional[dict], provider: str) -> Optional[dict]:
    """Records which provider actually produced `result`, so consumers
    (e.g. mediainfo's vinyl source) can label the artwork by its real
    source rather than just `recognition_provider`, which doesn't capture
    fallbacks like ACRCloud -> local_folder."""
    if result is None:
        return None
    return {**result, "provider": provider}
