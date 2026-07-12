"""Config schema versioning: `config_version` + ordered migrations.

No field has ever been renamed or restructured, so every config.yaml in the
wild today is implicitly version 1 - this module starts as pure
infrastructure. The problem it heads off: nested section configs are
pydantic dataclasses with `extra="forbid"`, so the day a field is renamed,
every existing install's old key gets rejected outright and the app refuses
to start. Instead of that, add a migration function here (old shape -> new
shape, keyed by the version it upgrades *from*) at the same time as the
rename, and existing config.yaml files keep working unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

CURRENT_CONFIG_VERSION = 1

# Maps "version N" -> a function that takes a raw config dict written at
# version N and returns the equivalent dict at version N+1. Keep entries in
# order; migrate_config() walks them starting from whatever version the
# file declares (or 1, if it declares none).
_MIGRATIONS: Dict[int, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}


def migrate_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return `raw` upgraded to CURRENT_CONFIG_VERSION.

    A missing `config_version` is treated as 1 (every config predating this
    feature is implicitly v1). A version newer than CURRENT_CONFIG_VERSION
    (running older app code against a newer config.yaml) is left untouched
    with a warning rather than raised as an error - startup should degrade
    gracefully, not crash, per this project's usual rule for unrecognized
    input.
    """
    version = raw.get("config_version", 1)
    if not isinstance(version, int):
        logger.warning("Ignoring non-integer config_version %r - treating config as v1.", version)
        version = 1

    if version > CURRENT_CONFIG_VERSION:
        logger.warning(
            "config.yaml declares config_version %d, newer than this build of mediainfo "
            "understands (%d). Running with it as-is; upgrade mediainfo if settings "
            "behave unexpectedly.",
            version,
            CURRENT_CONFIG_VERSION,
        )
        return raw

    migrated = raw
    while version < CURRENT_CONFIG_VERSION:
        migration = _MIGRATIONS.get(version)
        if migration is None:
            break
        migrated = migration(dict(migrated))
        version += 1

    if migrated is not raw:
        migrated["config_version"] = version
    return migrated
