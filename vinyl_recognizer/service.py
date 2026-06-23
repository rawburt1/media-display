"""Background loop: records short clips, detects silence, and calls a
recognition provider (AudD, ACRCloud, AcoustID, Shazam, or vibra)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from vinyl_recognizer import acoustid, acrcloud, audd, recorder, shazam, vibra
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
            return acrcloud.recognize(
                wav_bytes,
                self.config.acrcloud_host,
                self.config.acrcloud_access_key,
                self.config.acrcloud_access_secret,
            )
        if self.config.recognition_provider == "acoustid":
            return acoustid.recognize(wav_bytes, self.config.acoustid_api_key)
        if self.config.recognition_provider == "shazam":
            return shazam.recognize(wav_bytes)
        if self.config.recognition_provider == "vibra":
            return vibra.recognize(wav_bytes)
        return audd.recognize(wav_bytes, self.config.audd_api_key)
