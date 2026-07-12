"""Device status model: separates *Health* (is the integration actually
broken?) from *Activity* (what's the device doing right now?) so a source
that's simply powered off doesn't look the same as one that's genuinely
misbehaving.

Sources report a raw `AvailabilityReason` (or, for anything not yet
migrated to this, nothing at all - see mediainfo/sources/base.py's
`availability_reason` default of None). This module is the single place
that translates a reason into the pair of user-facing concepts:

- Health: Healthy / Warning / Error
- Activity: Playing / Paused / Idle / Sleeping / Unknown

Individual integrations only ever report the raw reason; nothing outside
this module should hardcode the Health/Activity mapping, so the UI stays
consistent no matter which integration produced the reason.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import dataclasses
import enum

import requests


class AvailabilityReason(enum.Enum):
    """Why a source is (or isn't) able to report now-playing state, at a
    finer grain than the boolean MediaSource.last_poll_failed. Purely
    internal/backend - never serialized directly, always translated via
    translate_availability() first."""

    AVAILABLE = enum.auto()
    IDLE = enum.auto()
    PLAYING = enum.auto()
    PAUSED = enum.auto()
    POWERED_OFF = enum.auto()
    SLEEPING = enum.auto()
    NETWORK_UNREACHABLE = enum.auto()
    AUTH_FAILED = enum.auto()
    CONFIG_ERROR = enum.auto()
    API_ERROR = enum.auto()
    UNKNOWN = enum.auto()


class Health(str, enum.Enum):
    """Is the integration actually broken? Never implies anything about
    what the device is currently doing - a powered-off device is Healthy."""

    HEALTHY = "healthy"
    WARNING = "warning"
    ERROR = "error"


class Activity(str, enum.Enum):
    """What the device is doing right now. Never implies a problem - even
    Unknown just means "can't currently tell", not "broken" (see Health
    for that)."""

    PLAYING = "playing"
    PAUSED = "paused"
    IDLE = "idle"
    SLEEPING = "sleeping"
    UNKNOWN = "unknown"


@dataclasses.dataclass(frozen=True)
class DeviceStatus:
    """The translated (Health, Activity) pair for a reason, plus a
    ready-to-show label - the UI should never need to invent its own
    wording per reason."""

    health: Health
    activity: Activity
    label: str


# The one place a raw AvailabilityReason becomes the user-facing
# Health/Activity pair - see the module docstring. UNKNOWN maps to
# Warning rather than Error: "can't currently tell" shouldn't look the
# same as "confirmed broken".
_TRANSLATIONS = {
    AvailabilityReason.AVAILABLE: DeviceStatus(
        Health.HEALTHY, Activity.IDLE, "Waiting for Playback"
    ),
    AvailabilityReason.IDLE: DeviceStatus(Health.HEALTHY, Activity.IDLE, "Idle"),
    AvailabilityReason.PLAYING: DeviceStatus(Health.HEALTHY, Activity.PLAYING, "Playing"),
    AvailabilityReason.PAUSED: DeviceStatus(Health.HEALTHY, Activity.PAUSED, "Paused"),
    AvailabilityReason.POWERED_OFF: DeviceStatus(Health.HEALTHY, Activity.SLEEPING, "Powered Off"),
    AvailabilityReason.SLEEPING: DeviceStatus(Health.HEALTHY, Activity.SLEEPING, "Sleeping"),
    AvailabilityReason.NETWORK_UNREACHABLE: DeviceStatus(
        Health.WARNING, Activity.UNKNOWN, "Unavailable"
    ),
    AvailabilityReason.AUTH_FAILED: DeviceStatus(
        Health.ERROR, Activity.UNKNOWN, "Authentication Failed"
    ),
    AvailabilityReason.CONFIG_ERROR: DeviceStatus(
        Health.ERROR, Activity.UNKNOWN, "Configuration Error"
    ),
    AvailabilityReason.API_ERROR: DeviceStatus(Health.ERROR, Activity.UNKNOWN, "Integration Error"),
    AvailabilityReason.UNKNOWN: DeviceStatus(Health.WARNING, Activity.UNKNOWN, "Unknown"),
}


def translate_availability(reason: AvailabilityReason) -> DeviceStatus:
    """The translation layer: raw AvailabilityReason -> (Health, Activity, label)."""
    return _TRANSLATIONS[reason]


# requests.exceptions.RequestException (the base of HTTPError, ConnectionError,
# Timeout, ...) itself subclasses OSError, so a plain OSError check would
# wrongly catch an HTTPError (a reachable server that responded with an
# error) as "unreachable" - ConnectionError/Timeout are checked first and
# explicitly, everything else from requests falls through to API_ERROR
# before the generic OSError check ever sees it.
_REQUESTS_NETWORK_EXCEPTIONS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)

# asyncio.TimeoutError/concurrent.futures.TimeoutError are their own
# distinct classes pre-3.11, not related to the builtin TimeoutError/
# OSError the way socket.timeout already is.
_TIMEOUT_EXCEPTIONS = (asyncio.TimeoutError, concurrent.futures.TimeoutError)


def classify_connection_exception(exc: BaseException) -> AvailabilityReason:
    """Best-effort classification of a caught exception into
    NETWORK_UNREACHABLE (the device/host itself couldn't be reached) vs.
    API_ERROR (reached something, but the response/protocol handling
    failed) - a convenience for a source's `except` block, not part of
    the translation layer itself. Sources that can tell more precisely
    (an HTTP 401, a library's own auth-specific exception) should set
    AUTH_FAILED/CONFIG_ERROR directly instead of going through this.
    """
    if isinstance(exc, _REQUESTS_NETWORK_EXCEPTIONS):
        return AvailabilityReason.NETWORK_UNREACHABLE
    if isinstance(exc, requests.exceptions.RequestException):
        return AvailabilityReason.API_ERROR
    if isinstance(exc, _TIMEOUT_EXCEPTIONS + (OSError,)):
        return AvailabilityReason.NETWORK_UNREACHABLE
    return AvailabilityReason.API_ERROR
