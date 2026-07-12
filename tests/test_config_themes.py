"""Tests for mediainfo.config.themes.parse_themes()."""

import pydantic
import pytest

from mediainfo.config.themes import parse_themes


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class _FakeThemeConfig:
    enabled: bool = False
    intensity: float = 0.5


@pytest.fixture(autouse=True)
def fake_theme_registry(monkeypatch):
    monkeypatch.setattr(
        "mediainfo.config.themes.THEMES_CONFIG_TYPES",
        {"glow": _FakeThemeConfig},
    )


def test_parse_themes_empty_dict():
    assert parse_themes({}) == {}


def test_parse_themes_none():
    assert parse_themes(None) == {}


def test_parse_themes_constructs_known_theme():
    result = parse_themes({"glow": {"enabled": True, "intensity": 0.8}})
    assert result["glow"] == _FakeThemeConfig(enabled=True, intensity=0.8)


def test_parse_themes_skips_unknown_theme(caplog):
    result = parse_themes({"nonexistent": {"enabled": True}})
    assert result == {}
    assert "nonexistent" in caplog.text


def test_parse_themes_defaults_missing_values():
    result = parse_themes({"glow": {}})
    assert result["glow"] == _FakeThemeConfig()


def test_parse_themes_raises_on_unknown_field():
    with pytest.raises(ValueError, match="no_such_field"):
        parse_themes({"glow": {"no_such_field": "x"}})
