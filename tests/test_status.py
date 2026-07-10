"""Tests for mediainfo.status: the AvailabilityReason -> (Health, Activity)
translation layer, and the shared connection-exception classifier."""

import socket

import pytest
import requests

from mediainfo.status import (
    Activity,
    AvailabilityReason,
    Health,
    classify_connection_exception,
    translate_availability,
)

# ---------------------------------------------------------------------------
# translate_availability
# ---------------------------------------------------------------------------

_EXPECTED = {
    AvailabilityReason.AVAILABLE: (Health.HEALTHY, Activity.IDLE, "Waiting for Playback"),
    AvailabilityReason.IDLE: (Health.HEALTHY, Activity.IDLE, "Idle"),
    AvailabilityReason.PLAYING: (Health.HEALTHY, Activity.PLAYING, "Playing"),
    AvailabilityReason.PAUSED: (Health.HEALTHY, Activity.PAUSED, "Paused"),
    AvailabilityReason.POWERED_OFF: (Health.HEALTHY, Activity.SLEEPING, "Powered Off"),
    AvailabilityReason.SLEEPING: (Health.HEALTHY, Activity.SLEEPING, "Sleeping"),
    AvailabilityReason.NETWORK_UNREACHABLE: (Health.WARNING, Activity.UNKNOWN, "Unavailable"),
    AvailabilityReason.AUTH_FAILED: (Health.ERROR, Activity.UNKNOWN, "Authentication Failed"),
    AvailabilityReason.CONFIG_ERROR: (Health.ERROR, Activity.UNKNOWN, "Configuration Error"),
    AvailabilityReason.API_ERROR: (Health.ERROR, Activity.UNKNOWN, "Integration Error"),
    AvailabilityReason.UNKNOWN: (Health.WARNING, Activity.UNKNOWN, "Unknown"),
}


@pytest.mark.parametrize("reason", list(AvailabilityReason))
def test_translate_availability_covers_every_reason(reason):
    expected_health, expected_activity, expected_label = _EXPECTED[reason]
    status = translate_availability(reason)
    assert status.health == expected_health
    assert status.activity == expected_activity
    assert status.label == expected_label


def test_powered_off_is_healthy_not_error():
    """The whole point of this model: a powered-off device must not look
    broken."""
    status = translate_availability(AvailabilityReason.POWERED_OFF)
    assert status.health == Health.HEALTHY


def test_unknown_is_warning_not_error():
    """"Can't currently tell" shouldn't look identical to "confirmed
    broken"."""
    status = translate_availability(AvailabilityReason.UNKNOWN)
    assert status.health == Health.WARNING


@pytest.mark.parametrize(
    "reason",
    [
        AvailabilityReason.AUTH_FAILED,
        AvailabilityReason.CONFIG_ERROR,
        AvailabilityReason.API_ERROR,
    ],
)
def test_real_error_reasons_map_to_error_health(reason):
    assert translate_availability(reason).health == Health.ERROR


def test_activity_colors_never_imply_failure():
    """No Activity value should ever be paired with Health.ERROR - Activity
    is purely descriptive, never a failure signal on its own."""
    for reason in AvailabilityReason:
        status = translate_availability(reason)
        if status.health == Health.ERROR:
            assert status.activity == Activity.UNKNOWN


# ---------------------------------------------------------------------------
# classify_connection_exception
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        ConnectionRefusedError("refused"),
        TimeoutError("timed out"),
        socket.timeout("timed out"),
        OSError("no route to host"),
        requests.exceptions.ConnectionError("connection error"),
        requests.exceptions.Timeout("timeout"),
    ],
)
def test_classify_connection_exception_recognizes_network_errors(exc):
    assert classify_connection_exception(exc) == AvailabilityReason.NETWORK_UNREACHABLE


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("bad response"),
        RuntimeError("unexpected"),
        requests.exceptions.HTTPError("500 server error"),
        KeyError("missing field"),
    ],
)
def test_classify_connection_exception_falls_back_to_api_error(exc):
    assert classify_connection_exception(exc) == AvailabilityReason.API_ERROR
