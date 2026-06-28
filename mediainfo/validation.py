"""Config validation: warns about common mistakes that otherwise fail
silently (a plugin enabled but missing from `priority`, a plugin enabled
with a blank credential, auth enabled with no real username/password).

Split out from __main__.py so this knowledge lives next to what it
validates rather than in the CLI entry point - run at startup and after
every config-file reload, since these mistakes are just as easy to make
through the config UI as by hand.
"""

from __future__ import annotations

import logging

from mediainfo.config import Config

logger = logging.getLogger(__name__)

# (category, type name) -> required field name(s) for that type to be able
# to do anything once enabled. Deliberately excludes appletv's credentials
# (blank is a normal, expected state before `python -m mediainfo auth
# appletv` has been run, not a mistake) and anything with no credential at
# all (musicbrainz, wikipedia, library, sonos, kodi, shield, youtube, vinyl).
_REQUIRED_CREDENTIAL_FIELDS: dict[tuple, list] = {
    ("sources", "plex"): ["token"],
    ("sources", "emby"): ["api_key"],
    ("sources", "homeassistant"): ["token", "entity_id"],
    ("sources", "jellyfin"): ["api_key"],
    ("sources", "ps5"): ["npsso"],
    ("sources", "spotify"): ["client_id", "client_secret"],
    ("enrichers", "fanarttv"): ["api_key"],
    ("enrichers", "thetvdb"): ["api_key"],
    ("enrichers", "discogs"): ["token"],
    ("enrichers", "lastfm"): ["api_key"],
    ("enrichers", "sonarr"): ["api_key"],
    ("enrichers", "radarr"): ["api_key"],
    ("enrichers", "lidarr"): ["api_key"],
    ("idle", "unsplash"): ["access_key"],
    ("idle", "lastfm"): ["api_key"],
}


def validate_config(config: Config) -> None:
    """Log warnings for common config mistakes that otherwise fail
    silently. Run at startup and after every reload, since the mistakes
    this guards against are just as easy to make through the config UI
    later as they are by hand up front.
    """
    for name, source_config in config.sources.items():
        if source_config.enabled and name not in config.priority:
            logger.warning(
                "sources.%s is enabled but not listed in priority - it will never be "
                "polled. Add it to the priority list to actually use it.",
                name,
            )

    for (category, name), fields in _REQUIRED_CREDENTIAL_FIELDS.items():
        item = getattr(config, category).get(name)
        if item is None or not getattr(item, "enabled", False):
            continue
        missing = [f for f in fields if not getattr(item, f, None)]
        if missing:
            logger.warning(
                "%s.%s is enabled but %s %s blank - it will fail on every attempt.",
                category, name, " and ".join(missing), "is" if len(missing) == 1 else "are",
            )

    if config.auth.enabled and not (config.auth.username and config.auth.password):
        logger.warning(
            "auth.enabled is true but username/password is blank - this means *any* "
            "request presenting empty credentials will authenticate successfully, "
            "which is no real protection. Set a real username/password."
        )

    for (category, name), fields in _REQUIRED_CREDENTIAL_FIELDS.items():
        item = getattr(config, category).get(name)
        if item is None or not getattr(item, "enabled", False):
            continue
        for f in fields:
            val = getattr(item, f, None)
            if val and "${" in val:
                logger.warning(
                    "%s.%s.%s contains an unexpanded env var reference ('%s') — "
                    "the environment variable was not set at startup.",
                    category, name, f, val,
                )
