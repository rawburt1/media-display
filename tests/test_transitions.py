"""Tests for the shared image-transition CSS/JS helper."""

from mediainfo.outputs.transitions import ALL_TRANSITIONS, transitions_css, transitions_js


def test_transitions_css_uses_default_container_selector():
    css = transitions_css()
    assert "#art-container img.t-slide-left" in css
    assert "#art-container img.visible" in css


def test_transitions_css_uses_custom_container_selector():
    css = transitions_css("#art-wrap")
    assert "#art-wrap img.t-zoom" in css
    assert "#art-container" not in css


def test_transitions_js_includes_all_variants_by_default():
    js = transitions_js([])
    for name in ALL_TRANSITIONS:
        assert f'"t-{name}"' in js


def test_transitions_js_excludes_requested_variants():
    js = transitions_js(["slide-left", "zoom"])
    # The variants pool (TRANSITION_VARIANTS) must exclude them...
    variants_section = js.split("TRANSITION_VARIANTS = ")[1].split(";")[0]
    assert "t-slide-left" not in variants_section
    assert "t-zoom" not in variants_section
    # ...but the full class list (used to clear old classes) still lists them.
    all_classes_section = js.split("ALL_TRANSITION_CLASSES = ")[1].split(";")[0]
    assert "t-slide-left" in all_classes_section
    assert "t-zoom" in all_classes_section


def test_transitions_js_falls_back_to_fade_when_all_excluded():
    js = transitions_js(list(ALL_TRANSITIONS))
    variants_section = js.split("TRANSITION_VARIANTS = ")[1].split(";")[0]
    assert "t-fade" in variants_section


def test_transitions_js_defines_prepare_function():
    js = transitions_js([])
    assert "function prepareForTransition(img)" in js
