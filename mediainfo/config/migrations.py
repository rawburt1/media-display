"""Config schema versioning: `config_version` + ordered migrations.

Every config.yaml predating this feature is implicitly version 1. The
problem this heads off: nested section configs are pydantic dataclasses
with `extra="forbid"`, so the day a field is renamed or removed, every
existing install's old key gets rejected outright and the app refuses to
start. Instead of that, add a migration function here (old shape -> new
shape, keyed by the version it upgrades *from*) at the same time as the
rename, and existing config.yaml files keep working unchanged.

v1 -> v2 (see _migrate_v1_to_v2) is the first real migration: H1's HTTP
server consolidation removed every Flask-based output's own host/port
fields in favor of one shared config.http.

v2 -> v3 (see _migrate_v2_to_v3): M1's auth.password is now stored hashed,
not plaintext.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

CURRENT_CONFIG_VERSION = 3

# Per output type, which of its own fields config_version 2 drops now that
# every Flask-based output shares one HTTP server (Config.http) instead of
# owning its own bind address - see mediainfo/outputs/http_server.py and H1
# in docs/architecture-usability-review-2026-07.md. nest_hub keeps
# server_host (the LAN address a Cast device dials - not a bind address,
# still needed) and only drops server_port.
_V1_OUTPUT_HOST_PORT_FIELDS: Dict[str, tuple] = {
    "web": ("host", "port"),
    "config": ("host", "port"),
    "themes": ("host", "port"),
    "info": ("host", "port"),
    "feed": ("host", "port"),
    "video": ("host", "port"),
    "nest_hub": ("server_port",),
}


def _migrate_v1_to_v2(raw: Dict[str, Any]) -> Dict[str, Any]:
    """H1: every Flask-based output now shares one HTTP server
    (config.http.host/port) instead of owning its own - drop the
    now-meaningless per-output host/port keys.

    Separately warns (rather than silently dropping) if outputs.config.host
    was ever set to anything other than the all-LAN-reachable shipped
    default: that used to be the supported way to keep the config UI
    (unauthenticated read+write access to config.yaml, including every
    credential in it) off the LAN while other outputs stayed reachable - see
    SECURITY.md's old "Operating modes" table. One shared host removes that
    option, so anyone who deliberately chose it should notice at upgrade
    time rather than finding the config UI newly LAN-reachable.
    """
    raw = dict(raw)
    outputs = raw.get("outputs")
    if not isinstance(outputs, dict):
        return raw

    new_outputs = dict(outputs)
    for name, fields_to_drop in _V1_OUTPUT_HOST_PORT_FIELDS.items():
        value = new_outputs.get(name)
        if value is None:
            continue
        entries = value if isinstance(value, list) else [value]
        migrated_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                migrated_entries.append(entry)
                continue
            entry = dict(entry)
            for field in fields_to_drop:
                if field in entry:
                    dropped = entry.pop(field)
                    logger.info(
                        "Migrating config: dropped outputs.%s.%s=%r (label=%r) - v2 now "
                        "serves every Flask-based output through one shared config.http "
                        "host/port.",
                        name,
                        field,
                        dropped,
                        entry.get("label", ""),
                    )
            migrated_entries.append(entry)
        new_outputs[name] = migrated_entries if isinstance(value, list) else migrated_entries[0]

    config_entries = outputs.get("config")
    if config_entries is not None:
        for entry in config_entries if isinstance(config_entries, list) else [config_entries]:
            if isinstance(entry, dict) and entry.get("host", "0.0.0.0") != "0.0.0.0":
                logger.warning(
                    "outputs.config.host was set to %r - as of config_version 2, every "
                    "Flask-based output shares one host (config.http.host); the config UI "
                    "(unauthenticated read+write access to config.yaml) is now reachable "
                    "wherever that shared host allows. Set auth.enabled: true if you need "
                    "to restrict access. See SECURITY.md.",
                    entry.get("host"),
                )

    raw["outputs"] = new_outputs
    return raw


def _migrate_v2_to_v3(raw: Dict[str, Any]) -> Dict[str, Any]:
    """M1 (docs/architecture-usability-review-2026-07.md): auth.password is
    now stored hashed (see mediainfo.web_auth.hash_password/verify_password),
    not plaintext - hash whatever plaintext value config_version 2 left
    there, so the in-memory Config this process runs with is never compared
    with a plaintext `==` again, even before config.yaml itself is next
    resaved (this migration - like v1->v2 - only ever changes the raw dict
    in memory; nothing here writes config.yaml back to disk, matching how
    every other load-time migration in this file already behaves. Run
    `python -m mediainfo set-password` once, or re-save via the config UI's
    Advanced section, to also rewrite the file on disk with the hash).

    A deferred import (rather than a module-level one) avoids a circular
    import: mediainfo.web_auth imports mediainfo.config (for AuthConfig),
    and this module is imported *by* mediainfo.config.__init__ itself - by
    the time this function actually runs (from Config.load()/from_dict(),
    well after mediainfo.config has finished initializing), the cycle is
    no longer a problem.
    """
    raw = dict(raw)
    auth = raw.get("auth")
    if not isinstance(auth, dict):
        return raw
    password = auth.get("password")
    if not password:
        return raw

    from mediainfo.web_auth import hash_password

    raw["auth"] = {**auth, "password": hash_password(password)}
    return raw


# Maps "version N" -> a function that takes a raw config dict written at
# version N and returns the equivalent dict at version N+1. Keep entries in
# order; migrate_config() walks them starting from whatever version the
# file declares (or 1, if it declares none).
_MIGRATIONS: Dict[int, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
}


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
