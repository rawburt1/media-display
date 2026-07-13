"""Tests for mediainfo.config_error_translator (M3 - see
docs/architecture-usability-review-2026-07.md): translating a raw
pydantic.ValidationError into a plain-English message.

Deliberately drives these through the real Config.from_dict() rather than
constructing pydantic.ValidationError objects by hand - the point of this
translator is to handle whatever pydantic actually raises for this
codebase's real config dataclasses, not a hand-picked approximation of it.
"""

from __future__ import annotations

import pydantic
import pytest

from mediainfo.config import Config
from mediainfo.config_error_translator import translate_validation_error


def _translated(raw: dict) -> str:
    with pytest.raises(pydantic.ValidationError) as exc_info:
        Config.from_dict(raw)
    return translate_validation_error(exc_info.value)


def test_unknown_field_suggests_the_closest_real_field():
    message = _translated({"outputs": {"pixoo": [{"enalbed": True}]}})
    assert message == "`pixoo` doesn't have a setting called `enalbed` - did you mean `enabled`?"


def test_unknown_field_on_a_source():
    message = _translated({"sources": {"kodi": {"enabled": True, "hos": "1.2.3.4"}}})
    assert message == "`kodi` doesn't have a setting called `hos` - did you mean `host`?"


def test_unknown_field_on_a_flat_section():
    message = _translated({"auth": {"enabled": True, "usernam": "x"}})
    assert message == "`auth` doesn't have a setting called `usernam` - did you mean `username`?"


def test_unknown_field_with_no_close_match_omits_the_suggestion():
    message = _translated({"sources": {"kodi": {"enabled": True, "zzzzz": "x"}}})
    assert message == "`kodi` doesn't have a setting called `zzzzz`"
    assert "did you mean" not in message


def test_wrong_type_int_field():
    message = _translated({"sources": {"kodi": {"enabled": True, "port": "not-a-number"}}})
    assert message.startswith("`kodi.port`:")
    assert "not-a-number" in message


def test_wrong_type_bool_field():
    message = _translated({"sources": {"kodi": {"enabled": "not-a-bool"}}})
    assert message.startswith("`kodi.enabled`:")


def test_multiple_errors_are_each_on_their_own_line():
    message = _translated({"sources": {"kodi": {"enabled": "not-a-bool", "port": "not-a-number"}}})
    lines = message.splitlines()
    assert len(lines) == 2
    assert any(line.startswith("`kodi.enabled`:") for line in lines)
    assert any(line.startswith("`kodi.port`:") for line in lines)


def test_unrecognized_class_falls_back_to_the_raw_title():
    """A class this translator's registries don't know about (shouldn't
    happen for this codebase's own dataclasses, but proves the fallback
    doesn't crash) uses its own __name__ as the key."""
    from mediainfo.config_error_translator import _translate_one

    err = {"loc": ("some_field",), "type": "missing", "msg": "Field required", "input": {}}
    assert _translate_one("SomeUnknownClass", None, err) == (  # type: ignore[arg-type]
        "`SomeUnknownClass` is missing its required `some_field` setting"
    )


def test_did_you_mean_returns_none_for_a_class_with_no_close_match():
    from mediainfo.config_error_translator import _did_you_mean
    from mediainfo.config import KodiConfig

    assert _did_you_mean("zzzzz", KodiConfig) is None


def test_did_you_mean_returns_none_for_unknown_class():
    from mediainfo.config_error_translator import _did_you_mean

    assert _did_you_mean("host", None) is None


def test_every_registered_config_class_is_in_the_lookup_maps():
    """Sanity check that the module-level maps actually cover every
    registered plugin/flat-section config class, not just the ones this
    test file happens to exercise - a real drift-detection safety net."""
    from mediainfo.config import (
        ENRICHER_CONFIG_TYPES,
        IDLE_CONFIG_TYPES,
        OUTPUT_CONFIG_TYPES,
        SOURCE_CONFIG_TYPES,
        TEXT_ENRICHER_CONFIG_TYPES,
        THEMES_CONFIG_TYPES,
    )
    from mediainfo.config_error_translator import _CLASS_NAME_TO_CLASS, _CLASS_NAME_TO_KEY

    for registry in (
        SOURCE_CONFIG_TYPES,
        OUTPUT_CONFIG_TYPES,
        ENRICHER_CONFIG_TYPES,
        TEXT_ENRICHER_CONFIG_TYPES,
        IDLE_CONFIG_TYPES,
        THEMES_CONFIG_TYPES,
    ):
        for key, cls in registry.items():
            assert _CLASS_NAME_TO_KEY[cls.__name__] == key
            assert _CLASS_NAME_TO_CLASS[cls.__name__] is cls
