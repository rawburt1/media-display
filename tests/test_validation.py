"""Tests for config validation warnings."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from mediainfo.validation import validate_config


def test_validate_config_warns_when_enabled_source_missing_from_priority(caplog):
    cfg = MagicMock()
    cfg.priority = ["kodi"]
    kodi_cfg = MagicMock(enabled=True)
    youtube_cfg = MagicMock(enabled=True)
    cfg.sources = {"kodi": kodi_cfg, "youtube": youtube_cfg}

    with caplog.at_level(logging.WARNING, logger="mediainfo.validation"):
        validate_config(cfg)

    assert any("youtube" in r.message and "priority" in r.message for r in caplog.records)
    assert not any("kodi" in r.message for r in caplog.records)


def test_validate_config_silent_when_disabled_source_missing_from_priority(caplog):
    cfg = MagicMock()
    cfg.priority = []
    cfg.sources = {"youtube": MagicMock(enabled=False)}

    with caplog.at_level(logging.WARNING, logger="mediainfo.validation"):
        validate_config(cfg)

    assert caplog.records == []


def test_validate_config_silent_when_all_enabled_sources_listed(caplog):
    cfg = MagicMock()
    cfg.priority = ["kodi", "youtube"]
    cfg.sources = {"kodi": MagicMock(enabled=True), "youtube": MagicMock(enabled=True)}

    with caplog.at_level(logging.WARNING, logger="mediainfo.validation"):
        validate_config(cfg)

    assert caplog.records == []


def _config_for_credential_test(**overrides):
    """A MagicMock Config with empty sources/enrichers/idle/auth by
    default, so only the field(s) set via `overrides` (e.g.
    enrichers={"thetvdb": ...}) are exercised - everything else falls
    through the "not in dict" early-continue, unlike a bare MagicMock()
    whose auto-vivified attributes would all look "present".
    """
    cfg = MagicMock()
    cfg.priority = []
    cfg.sources = overrides.get("sources", {})
    cfg.enrichers = overrides.get("enrichers", {})
    cfg.idle = overrides.get("idle", {})
    cfg.auth = overrides.get("auth", MagicMock(enabled=False))
    return cfg


def test_validate_config_warns_when_required_credential_is_blank(caplog):
    from mediainfo.config import TheTvDbConfig

    cfg = _config_for_credential_test(
        enrichers={"thetvdb": TheTvDbConfig(enabled=True, api_key="")}
    )

    with caplog.at_level(logging.WARNING, logger="mediainfo.validation"):
        validate_config(cfg)

    assert any("thetvdb" in r.message and "api_key" in r.message for r in caplog.records)


def test_validate_config_warns_with_multiple_missing_fields(caplog):
    from mediainfo.config import SpotifyConfig

    cfg = _config_for_credential_test(
        sources={"spotify": SpotifyConfig(enabled=True, client_id="", client_secret="")}
    )

    with caplog.at_level(logging.WARNING, logger="mediainfo.validation"):
        validate_config(cfg)

    assert any(
        "client_id" in r.message and "client_secret" in r.message for r in caplog.records
    )


def test_validate_config_silent_when_credential_is_set(caplog):
    from mediainfo.config import TheTvDbConfig

    cfg = _config_for_credential_test(
        enrichers={"thetvdb": TheTvDbConfig(enabled=True, api_key="real-key")}
    )

    with caplog.at_level(logging.WARNING, logger="mediainfo.validation"):
        validate_config(cfg)

    assert caplog.records == []


def test_validate_config_silent_when_credential_consumer_disabled(caplog):
    from mediainfo.config import TheTvDbConfig

    cfg = _config_for_credential_test(
        enrichers={"thetvdb": TheTvDbConfig(enabled=False, api_key="")}
    )

    with caplog.at_level(logging.WARNING, logger="mediainfo.validation"):
        validate_config(cfg)

    assert caplog.records == []


def test_validate_config_does_not_warn_about_appletv_credentials():
    # Blank appletv credentials are a normal pre-pairing state, not a
    # mistake - this dict simply has no entry for it (see comment above
    # _REQUIRED_CREDENTIAL_FIELDS), so it's never flagged.
    from mediainfo.validation import _REQUIRED_CREDENTIAL_FIELDS
    assert ("sources", "appletv") not in _REQUIRED_CREDENTIAL_FIELDS


def test_validate_config_warns_when_auth_enabled_with_blank_credentials(caplog):
    from mediainfo.config import AuthConfig

    cfg = _config_for_credential_test(auth=AuthConfig(enabled=True, username="", password=""))

    with caplog.at_level(logging.WARNING, logger="mediainfo.validation"):
        validate_config(cfg)

    assert any("auth" in r.message.lower() for r in caplog.records)


def test_validate_config_silent_when_auth_enabled_with_credentials(caplog):
    from mediainfo.config import AuthConfig

    cfg = _config_for_credential_test(
        auth=AuthConfig(enabled=True, username="admin", password="secret")
    )

    with caplog.at_level(logging.WARNING, logger="mediainfo.validation"):
        validate_config(cfg)

    assert caplog.records == []


def test_validate_config_silent_when_auth_disabled_with_blank_credentials(caplog):
    from mediainfo.config import AuthConfig

    cfg = _config_for_credential_test(auth=AuthConfig(enabled=False, username="", password=""))

    with caplog.at_level(logging.WARNING, logger="mediainfo.validation"):
        validate_config(cfg)

    assert caplog.records == []
