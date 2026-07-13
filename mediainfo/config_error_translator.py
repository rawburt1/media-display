"""Translates a pydantic.ValidationError raised while building Config (a
typo'd field name inside a section, or a wrong type) into a plain-English
message a non-technical user can act on, instead of pydantic's own
developer-facing wording (M3 in
docs/architecture-usability-review-2026-07.md):

    1 validation error for PixooConfig
    briteness
      Unexpected keyword argument [type=unexpected_keyword_argument, ...]

becomes:

    `pixoo` doesn't have a setting called `briteness` - did you mean `brightness`?

A typo'd top-level *section* name (e.g. `outputs.pixxoo`) already gets a
friendly "Unknown output plugin 'pixxoo' — ignored" warning elsewhere
(Config.from_dict() itself) - this covers the other case: a typo'd or
wrong-type *field inside* an otherwise-recognized section.

Deliberately doesn't touch Config.from_dict()'s own exception-raising
behavior (still raises the raw pydantic.ValidationError, exactly as every
existing test already expects) - this is a standalone translator callers
apply to an already-caught exception right before showing it to a user
(see config_store.py's save_form()/save_raw() and __main__.py's
validate-config/set-password).
"""

from __future__ import annotations

import dataclasses
import difflib
from typing import Optional

import pydantic
from pydantic_core import ErrorDetails

from mediainfo.config import (
    ENRICHER_CONFIG_TYPES,
    IDLE_CONFIG_TYPES,
    OUTPUT_CONFIG_TYPES,
    SOURCE_CONFIG_TYPES,
    TEXT_ENRICHER_CONFIG_TYPES,
    THEMES_CONFIG_TYPES,
)
from mediainfo.outputs.config_schema import _FLAT_SECTIONS


def _class_name_maps() -> tuple[dict[str, str], dict[str, type]]:
    """Every pydantic-validated config dataclass this app knows about, by
    its own __name__ - both the friendly key a user would recognize it by
    in config.yaml (a plugin's registry key, or a flat section name like
    "auth"), and the class itself (for did-you-mean's valid-field-name
    list). Built once at import time from the same registries/
    _FLAT_SECTIONS the rest of the config system already uses, rather
    than re-derived by hand, so this can't drift out of sync with what's
    actually registered.
    """
    name_to_key: dict[str, str] = {}
    name_to_class: dict[str, type] = {}
    registries = (
        SOURCE_CONFIG_TYPES,
        OUTPUT_CONFIG_TYPES,
        ENRICHER_CONFIG_TYPES,
        TEXT_ENRICHER_CONFIG_TYPES,
        IDLE_CONFIG_TYPES,
        THEMES_CONFIG_TYPES,
        _FLAT_SECTIONS,
    )
    for registry in registries:
        for key, cls in registry.items():
            name_to_key[cls.__name__] = key
            name_to_class[cls.__name__] = cls
    return name_to_key, name_to_class


_CLASS_NAME_TO_KEY, _CLASS_NAME_TO_CLASS = _class_name_maps()


def translate_validation_error(exc: pydantic.ValidationError) -> str:
    """Return a friendly, multi-line message for *exc* - one line per
    underlying field error (pydantic batches every error from one failed
    construction into a single ValidationError)."""
    key = _CLASS_NAME_TO_KEY.get(exc.title, exc.title)
    cls = _CLASS_NAME_TO_CLASS.get(exc.title)
    return "\n".join(_translate_one(key, cls, err) for err in exc.errors())


def friendly_config_error(exc: Exception) -> str:
    """translate_validation_error(exc) if exc is a pydantic.ValidationError
    (the only exception type Config.from_dict() actually raises for a bad
    config.yaml), else str(exc) unchanged - a single call every
    Config.from_dict()-catching call site can use without each needing its
    own isinstance check."""
    if isinstance(exc, pydantic.ValidationError):
        return translate_validation_error(exc)
    return str(exc)


def _did_you_mean(field: str, cls: Optional[type]) -> Optional[str]:
    if cls is None:
        return None
    valid_names = [f.name for f in dataclasses.fields(cls)]
    matches = difflib.get_close_matches(field, valid_names, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _translate_one(key: str, cls: Optional[type], err: ErrorDetails) -> str:
    field = ".".join(str(part) for part in err["loc"])
    error_type = err["type"]

    if error_type == "unexpected_keyword_argument":
        suggestion = _did_you_mean(field, cls)
        message = f"`{key}` doesn't have a setting called `{field}`"
        if suggestion:
            message += f" - did you mean `{suggestion}`?"
        return message

    if error_type == "missing":
        return f"`{key}` is missing its required `{field}` setting"

    # Wrong type / couldn't parse a string as one, etc. - pydantic's own
    # `msg` is already reasonably plain English ("Input should be a valid
    # integer"); this just restores the field context pydantic's own
    # multi-line format carries but a squashed single string loses, and
    # shows what was actually there instead. Also the fallback for any
    # error type not explicitly handled above, so a pydantic version
    # bump introducing a new error type degrades to "still readable,
    # just less tailored" instead of crashing this translator.
    return f"`{key}.{field}`: {err['msg']} (got {err.get('input')!r})"
