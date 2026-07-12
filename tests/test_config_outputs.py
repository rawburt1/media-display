"""Tests for mediainfo.config.outputs.parse_presets()."""

import pytest

from mediainfo.config.outputs import AutoRotatePresetConfig, parse_presets


def test_parse_presets_empty_dict():
    assert parse_presets({}) == {}


def test_parse_presets_none():
    assert parse_presets(None) == {}


def test_parse_presets_plain_list_is_unconditioned():
    # Today's shape (pre-`when`) - always accepted, never rotated away
    # from by a media-type match since `when` stays empty.
    result = parse_presets({"minimal": ["color_palette"]})
    assert result["minimal"] == AutoRotatePresetConfig(themes=["color_palette"], when=[])


def test_parse_presets_dict_shape_with_when():
    result = parse_presets({"music": {"themes": ["vinyl", "glow"], "when": ["music"]}})
    assert result["music"] == AutoRotatePresetConfig(themes=["vinyl", "glow"], when=["music"])


def test_parse_presets_dict_shape_defaults_missing_fields():
    result = parse_presets({"empty": {}})
    assert result["empty"] == AutoRotatePresetConfig(themes=[], when=[])


def test_parse_presets_preserves_declaration_order():
    result = parse_presets({"b": ["glow"], "a": ["vinyl"]})
    assert list(result.keys()) == ["b", "a"]


def test_parse_presets_raises_on_unknown_field():
    with pytest.raises(ValueError, match="no_such_field"):
        parse_presets({"music": {"no_such_field": "x"}})
