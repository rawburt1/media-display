"""Daily power/brightness scheduling for physical LED displays.

active_hours (see output_filter.py) can stop an output *showing* content
at night, but the panel itself stays lit with idle wallpapers or its clock
face. This module actually drives the hardware: a `screen_off_hours`
window turns the panel off and back on, and `brightness_schedule` windows
dim it, e.g. full brightness by day and a faint glow in the evening.

Split into two pieces:

- DisplaySchedule: pure evaluation - parse the config once, then answer
  "what should the panel look like at time T". Malformed entries are
  logged and skipped at construction (matching active_hours' philosophy
  of never letting a config typo take a display down).
- ScheduledDisplay: the stateful driver an output owns. Called from
  Output.on_schedule_tick() every orchestrator tick, it compares desired
  state against what was last applied and invokes the device callbacks
  only on change - so an unchanged schedule costs nothing per tick, and a
  device reboot doesn't get spammed with redundant commands. A failed
  command is retried, but at most every _RETRY_INTERVAL_SECONDS, so an
  unreachable device doesn't get hammered every poll tick.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Callable, List, Optional, Tuple

from mediainfo.output_filter import in_time_window

logger = logging.getLogger(__name__)

_RETRY_INTERVAL_SECONDS = 60


class DisplaySchedule:
    """Evaluates screen_off_hours / brightness_schedule config values.

    screen_off_hours: one daily "HH:MM-HH:MM" window (wraps midnight)
    during which the panel should be off. Empty means always on.

    brightness_schedule: entries of the form "HH:MM-HH:MM=<level>". The
    first window containing the current time wins; outside every window
    the brightness is left alone (None), so a partial schedule only ever
    overrides the hours it names. Level units are device-native (Pixoo:
    0-100, AWTRIX3: 0-255) - documented on each output's config.
    """

    def __init__(self, screen_off_hours: str = "", brightness_schedule: Optional[list] = None):
        self.screen_off_hours = self._valid_window(screen_off_hours)
        self.brightness_windows: List[Tuple[str, int]] = []
        for entry in brightness_schedule or []:
            parsed = self._parse_brightness_entry(entry)
            if parsed is not None:
                self.brightness_windows.append(parsed)

    @staticmethod
    def _valid_window(window: str) -> str:
        if not window:
            return ""
        try:
            in_time_window(window, now=datetime.time(0, 0))
        except (ValueError, AttributeError):
            logger.warning("Ignoring malformed screen_off_hours %r - expected HH:MM-HH:MM", window)
            return ""
        return window

    @staticmethod
    def _parse_brightness_entry(entry) -> Optional[Tuple[str, int]]:
        try:
            window, _, level_str = str(entry).partition("=")
            level = int(level_str)
            in_time_window(window, now=datetime.time(0, 0))  # validate format
            return (window, level)
        except (ValueError, AttributeError):
            logger.warning(
                "Ignoring malformed brightness_schedule entry %r - "
                "expected HH:MM-HH:MM=<level> (e.g. '20:00-08:00=15')",
                entry,
            )
            return None

    @property
    def configured(self) -> bool:
        return bool(self.screen_off_hours or self.brightness_windows)

    def desired(self, now: Optional[datetime.time] = None) -> Tuple[bool, Optional[int]]:
        """(screen_on, brightness) that should apply at `now` (default:
        current local time). brightness None means "leave it alone"."""
        screen_on = not (self.screen_off_hours and in_time_window(self.screen_off_hours, now))
        brightness = next(
            (level for window, level in self.brightness_windows if in_time_window(window, now)),
            None,
        )
        return screen_on, brightness


class ScheduledDisplay:
    """Applies a DisplaySchedule to a device via callbacks, on change only.

    set_power(bool) / set_brightness(int) may raise on device errors -
    tick() logs the failure and retries no sooner than
    _RETRY_INTERVAL_SECONDS later, keeping the desired state pending so a
    missed power-off still lands once the device is reachable again.
    """

    def __init__(
        self,
        schedule: DisplaySchedule,
        set_power: Callable[[bool], None],
        set_brightness: Callable[[int], None],
        label: str,
    ):
        self.schedule = schedule
        self._set_power = set_power
        self._set_brightness = set_brightness
        self._label = label
        self._applied_power: Optional[bool] = None
        self._applied_brightness: Optional[int] = None
        self._next_retry: float = 0.0

    def tick(self, now: Optional[datetime.time] = None) -> None:
        if not self.schedule.configured:
            return
        monotonic = time.monotonic()
        if monotonic < self._next_retry:
            return

        screen_on, brightness = self.schedule.desired(now)
        # Brightness before power-off, so a panel dimming into its off
        # window wakes at the right level; harmless in every other order.
        if brightness is not None and brightness != self._applied_brightness:
            if not self._apply(self._set_brightness, brightness, "brightness", monotonic):
                return
            self._applied_brightness = brightness
        if screen_on != self._applied_power:
            if not self._apply(self._set_power, screen_on, "power", monotonic):
                return
            self._applied_power = screen_on
            logger.info("%s: screen %s (scheduled)", self._label, "on" if screen_on else "off")

    def _apply(self, func, value, what: str, monotonic: float) -> bool:
        try:
            func(value)
            return True
        except Exception:
            logger.warning(
                "%s: failed to set %s to %s - retrying in %ds",
                self._label,
                what,
                value,
                _RETRY_INTERVAL_SECONDS,
                exc_info=True,
            )
            self._next_retry = monotonic + _RETRY_INTERVAL_SECONDS
            return False
