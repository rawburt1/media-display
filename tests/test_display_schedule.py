"""Tests for display power/brightness scheduling (display_schedule.py)."""

import datetime
from unittest.mock import MagicMock, patch

from mediainfo.display_schedule import DisplaySchedule, ScheduledDisplay


def _t(hhmm):
    hour, minute = hhmm.split(":")
    return datetime.time(int(hour), int(minute))


# ---------------------------------------------------------------------------
# DisplaySchedule: parsing and evaluation
# ---------------------------------------------------------------------------


def test_unconfigured_schedule_is_inert():
    schedule = DisplaySchedule()
    assert not schedule.configured
    assert schedule.desired(_t("03:00")) == (True, None)


def test_screen_off_window():
    schedule = DisplaySchedule(screen_off_hours="23:00-07:00")
    assert schedule.desired(_t("12:00")) == (True, None)
    assert schedule.desired(_t("23:30")) == (False, None)
    assert schedule.desired(_t("03:00")) == (False, None)  # wraps midnight
    assert schedule.desired(_t("07:30")) == (True, None)


def test_brightness_windows_first_match_wins():
    schedule = DisplaySchedule(
        brightness_schedule=["08:00-20:00=90", "20:00-08:00=15", "12:00-13:00=50"]
    )
    assert schedule.desired(_t("10:00"))[1] == 90
    assert schedule.desired(_t("22:00"))[1] == 15
    # 12:30 matches both the day window and the later lunch window - the
    # first entry wins.
    assert schedule.desired(_t("12:30"))[1] == 90


def test_time_outside_all_brightness_windows_leaves_brightness_alone():
    schedule = DisplaySchedule(brightness_schedule=["08:00-10:00=90"])
    assert schedule.desired(_t("11:00"))[1] is None


def test_malformed_entries_are_skipped_not_fatal():
    schedule = DisplaySchedule(
        screen_off_hours="not-a-window",
        brightness_schedule=["garbage", "08:00-20:00", "08:00-20:00=bright", "20:00-08:00=15"],
    )
    # Malformed screen_off_hours -> always on; only the valid entry kept.
    assert schedule.screen_off_hours == ""
    assert schedule.brightness_windows == [("20:00-08:00", 15)]
    assert schedule.desired(_t("23:00")) == (True, 15)


# ---------------------------------------------------------------------------
# ScheduledDisplay: change detection and retry throttling
# ---------------------------------------------------------------------------


def _display(schedule):
    set_power = MagicMock()
    set_brightness = MagicMock()
    return ScheduledDisplay(schedule, set_power, set_brightness, "test"), set_power, set_brightness


def test_applies_initial_state_once_then_stays_quiet():
    display, set_power, set_brightness = _display(
        DisplaySchedule(screen_off_hours="23:00-07:00", brightness_schedule=["08:00-20:00=90"])
    )

    display.tick(_t("12:00"))
    set_power.assert_called_once_with(True)
    set_brightness.assert_called_once_with(90)

    display.tick(_t("12:00"))
    display.tick(_t("13:00"))
    set_power.assert_called_once()  # unchanged state: no more device calls
    set_brightness.assert_called_once()


def test_transitions_fire_when_windows_change():
    display, set_power, set_brightness = _display(
        DisplaySchedule(screen_off_hours="23:00-07:00", brightness_schedule=["20:00-23:00=15"])
    )

    display.tick(_t("12:00"))
    display.tick(_t("20:30"))  # dim for the evening
    assert set_brightness.call_args_list[-1].args == (15,)
    display.tick(_t("23:30"))  # off for the night
    assert set_power.call_args_list[-1].args == (False,)
    display.tick(_t("07:30"))  # back on in the morning
    assert set_power.call_args_list[-1].args == (True,)


def test_unconfigured_schedule_never_calls_device():
    display, set_power, set_brightness = _display(DisplaySchedule())
    display.tick(_t("12:00"))
    set_power.assert_not_called()
    set_brightness.assert_not_called()


def test_failed_command_is_retried_but_throttled():
    display, set_power, _ = _display(DisplaySchedule(screen_off_hours="23:00-07:00"))
    set_power.side_effect = OSError("unreachable")

    clock = [1000.0]
    with patch("mediainfo.display_schedule.time.monotonic", lambda: clock[0]):
        display.tick(_t("23:30"))
        assert set_power.call_count == 1

        clock[0] += 5  # next poll tick: still inside the retry window
        display.tick(_t("23:35"))
        assert set_power.call_count == 1

        clock[0] += 60  # past the throttle: retried, device back up
        set_power.side_effect = None
        display.tick(_t("23:40"))
        assert set_power.call_count == 2
        assert set_power.call_args.args == (False,)

        # The successful state is now recorded - no further calls.
        clock[0] += 60
        display.tick(_t("23:45"))
        assert set_power.call_count == 2
