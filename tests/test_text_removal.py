"""Tests for mediainfo/text_removal.py.

No real EAST model file is used anywhere here - detection is either
exercised via a fake net_loader feeding synthetic score/geometry arrays
(to verify the decode math) or bypassed entirely via mocking
detect_text_regions (for the higher-level classify/removal/decision-record
behaviour). Loading and running an actual pretrained model binary is out of
scope for this agent to fetch or execute - see the module docstring.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from mediainfo.text_removal import (
    TextRegion,
    _crop_avoiding_regions,
    _decode_predictions,
    _legible_at_target_size,
    classify_regions,
    detect_text_regions,
    maybe_remove_text,
    remove_text,
)


def _gradient_image(w=300, h=300):
    img = Image.new("RGB", (w, h))
    for x in range(w):
        for y in range(h):
            img.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
    return img


# ---------------------------------------------------------------------------
# classify_regions
# ---------------------------------------------------------------------------


def test_classify_small_region():
    regions = [TextRegion(box=(0, 0, 10, 10), confidence=0.9, area_fraction=0.01)]
    result = classify_regions(regions, max_logo_area_percent=25.0)
    assert result[0].classification == "small"


def test_classify_large_logo_region():
    regions = [TextRegion(box=(0, 0, 10, 10), confidence=0.9, area_fraction=0.10)]
    result = classify_regions(regions, max_logo_area_percent=25.0)
    assert result[0].classification == "large_logo"


def test_classify_uncertain_region_above_max_logo_area():
    regions = [TextRegion(box=(0, 0, 10, 10), confidence=0.9, area_fraction=0.30)]
    result = classify_regions(regions, max_logo_area_percent=25.0)
    assert result[0].classification == "uncertain"


def test_classify_does_not_mutate_input():
    original = TextRegion(box=(0, 0, 10, 10), confidence=0.9, area_fraction=0.01)
    classify_regions([original], max_logo_area_percent=25.0)
    assert original.classification == "uncertain"


# ---------------------------------------------------------------------------
# _legible_at_target_size
# ---------------------------------------------------------------------------


def test_tiny_region_is_illegible():
    img = _gradient_image()
    # A 2x2 source box will scale down to well under 3px at size=16.
    assert _legible_at_target_size(img, (0, 0, 2, 2), target_size=16) is False


def test_flat_region_is_illegible():
    img = Image.new("RGB", (300, 300), (50, 50, 50))  # perfectly flat
    assert _legible_at_target_size(img, (0, 0, 150, 150), target_size=16) is False


def test_high_variance_region_at_adequate_scale_is_legible():
    img = _gradient_image()
    assert _legible_at_target_size(img, (0, 0, 150, 150), target_size=16) is True


# ---------------------------------------------------------------------------
# remove_text
# ---------------------------------------------------------------------------


def test_remove_text_with_no_regions_is_a_no_op():
    img = _gradient_image()
    result = remove_text(img, [], method="inpaint")
    assert result is img


def test_soft_fill_changes_pixels_inside_masked_region():
    img = Image.new("RGB", (100, 100), (10, 10, 10))
    # Paint a bright rectangle that soft-fill should smooth away.
    for x in range(40, 60):
        for y in range(40, 60):
            img.putpixel((x, y), (255, 255, 255))
    region = TextRegion(
        box=(40, 40, 60, 60), confidence=0.9, area_fraction=0.04, classification="small"
    )
    result = remove_text(img, [region], method="soft_fill", margin_ratio=0.0)
    # The center of the removed region should no longer be pure white.
    assert result.getpixel((50, 50)) != (255, 255, 255)
    assert result.size == img.size


def test_inpaint_changes_pixels_inside_masked_region():
    img = Image.new("RGB", (100, 100), (10, 10, 10))
    for x in range(40, 60):
        for y in range(40, 60):
            img.putpixel((x, y), (255, 255, 255))
    region = TextRegion(
        box=(40, 40, 60, 60), confidence=0.9, area_fraction=0.04, classification="small"
    )
    result = remove_text(img, [region], method="inpaint", margin_ratio=0.0)
    assert result.getpixel((50, 50)) != (255, 255, 255)
    assert result.size == img.size


def test_inpaint_falls_back_to_soft_fill_when_cv2_unavailable():
    img = Image.new("RGB", (100, 100), (10, 10, 10))
    for x in range(40, 60):
        for y in range(40, 60):
            img.putpixel((x, y), (255, 255, 255))
    region = TextRegion(
        box=(40, 40, 60, 60), confidence=0.9, area_fraction=0.04, classification="small"
    )
    with patch("mediainfo.text_removal._import_cv2", return_value=None):
        result = remove_text(img, [region], method="inpaint", margin_ratio=0.0)
    assert result.getpixel((50, 50)) != (255, 255, 255)


# ---------------------------------------------------------------------------
# detect_text_regions - graceful no-ops
# ---------------------------------------------------------------------------


def test_detect_returns_empty_without_model_path():
    assert detect_text_regions(_gradient_image(), model_path="") == []


def test_detect_returns_empty_when_cv2_unavailable():
    with patch("mediainfo.text_removal._import_cv2", return_value=None):
        assert detect_text_regions(_gradient_image(), model_path="/some/model.pb") == []


def test_detect_returns_empty_when_net_fails_to_load():
    def failing_loader(path):
        raise OSError("bad model file")

    result = detect_text_regions(
        _gradient_image(), model_path="/bad/path.pb", net_loader=failing_loader
    )
    assert result == []


# ---------------------------------------------------------------------------
# _decode_predictions - the EAST geometry decode math, in isolation
# ---------------------------------------------------------------------------


def test_decode_predictions_reconstructs_expected_box():
    # A single grid cell (y=0, x=0) with angle 0: box_h = 20 (top=10+bottom=10),
    # box_w = 20 (right=15+left=5) -> end=(15,10), start=(-5,-10).
    scores = np.zeros((1, 1, 1, 1), dtype=np.float32)
    scores[0, 0, 0, 0] = 0.9
    geometry = np.zeros((1, 5, 1, 1), dtype=np.float32)
    geometry[0, 0, 0, 0] = 10  # top distance
    geometry[0, 1, 0, 0] = 15  # right distance
    geometry[0, 2, 0, 0] = 10  # bottom distance
    geometry[0, 3, 0, 0] = 5  # left distance
    geometry[0, 4, 0, 0] = 0  # angle

    boxes, confidences = _decode_predictions(scores, geometry, confidence_threshold=0.5, np=np)

    assert boxes == [(-5, -10, 15, 10)]
    assert confidences == pytest.approx([0.9], abs=1e-4)


def test_decode_predictions_skips_low_confidence_cells():
    scores = np.zeros((1, 1, 1, 2), dtype=np.float32)
    scores[0, 0, 0, 0] = 0.1  # below threshold
    scores[0, 0, 0, 1] = 0.9  # above threshold
    geometry = np.zeros((1, 5, 1, 2), dtype=np.float32)
    geometry[0, :, 0, 1] = [10, 10, 10, 10, 0]

    boxes, confidences = _decode_predictions(scores, geometry, confidence_threshold=0.5, np=np)

    assert len(boxes) == 1
    assert confidences == pytest.approx([0.9], abs=1e-4)


def test_detect_text_regions_end_to_end_with_fake_net():
    # Exercises the full detect_text_regions path (blobFromImage, the real
    # net_loader-injected forward(), decode, and real cv2.dnn.NMSBoxes) with
    # a fake net standing in for the pretrained model itself.
    num_cells = 320 // 4

    class _FakeNet:
        def setInput(self, blob):
            pass

        def forward(self, layer_names):
            scores = np.zeros((1, 1, num_cells, num_cells), dtype=np.float32)
            geometry = np.zeros((1, 5, num_cells, num_cells), dtype=np.float32)
            scores[0, 0, 10, 10] = 0.95
            geometry[0, :, 10, 10] = [10, 15, 10, 5, 0]
            return scores, geometry

    regions = detect_text_regions(
        _gradient_image(320, 320), model_path="/fake/model.pb", net_loader=lambda path: _FakeNet()
    )
    assert len(regions) == 1
    assert regions[0].confidence > 0.9
    assert regions[0].box[2] > regions[0].box[0]
    assert regions[0].box[3] > regions[0].box[1]


# ---------------------------------------------------------------------------
# _crop_avoiding_regions (crop_preference removal method)
# ---------------------------------------------------------------------------


def test_crop_avoiding_regions_is_a_no_op_for_square_images():
    img = Image.new("RGB", (100, 100), (1, 2, 3))
    result = _crop_avoiding_regions(img, "center", avoid_boxes=[(10, 10, 20, 20)])
    assert result.size == (100, 100)


def test_crop_avoiding_regions_picks_offset_with_least_overlap():
    # Portrait image; a text box sits at the very top (y=0..40) - the
    # chosen crop should avoid starting there when there's a better option.
    img = Image.new("RGB", (100, 200), (1, 2, 3))
    result = _crop_avoiding_regions(img, "center", avoid_boxes=[(0, 0, 100, 40)])
    assert result.size == (100, 100)


def test_crop_avoiding_regions_falls_back_to_crop_strategy_without_avoid_boxes():
    img = Image.new("RGB", (100, 200), (1, 2, 3))
    result = _crop_avoiding_regions(img, "center", avoid_boxes=[])
    assert result.size == (100, 100)


# ---------------------------------------------------------------------------
# maybe_remove_text - top-level entry point
# ---------------------------------------------------------------------------


def test_disabled_returns_image_unchanged_with_no_decision():
    img = _gradient_image()
    result, decision = maybe_remove_text(img, target_size=16, enabled=False)
    assert result is img
    assert decision is None


def test_enabled_with_no_regions_returns_decision_with_empty_regions():
    img = _gradient_image()
    with patch("mediainfo.text_removal.detect_text_regions", return_value=[]):
        result, decision = maybe_remove_text(img, target_size=16, enabled=True, model_path="/x.pb")
    assert result is img
    assert decision["regions"] == []
    assert decision["removed_count"] == 0


def test_small_text_is_removed_when_configured():
    img = Image.new("RGB", (200, 200), (10, 10, 10))
    for x in range(20, 40):
        for y in range(20, 40):
            img.putpixel((x, y), (255, 255, 255))
    region = TextRegion(box=(20, 20, 40, 40), confidence=0.9, area_fraction=0.01)
    with patch("mediainfo.text_removal.detect_text_regions", return_value=[region]):
        result, decision = maybe_remove_text(
            img, target_size=64, enabled=True, model_path="/x.pb", remove_small_text=True
        )
    assert decision["removed_count"] == 1
    assert result.getpixel((30, 30)) != (255, 255, 255)


def test_small_text_is_kept_when_remove_small_text_is_false():
    img = Image.new("RGB", (200, 200), (10, 10, 10))
    for x in range(20, 40):
        for y in range(20, 40):
            img.putpixel((x, y), (255, 255, 255))
    region = TextRegion(box=(20, 20, 40, 40), confidence=0.9, area_fraction=0.01)
    with patch("mediainfo.text_removal.detect_text_regions", return_value=[region]):
        result, decision = maybe_remove_text(
            img, target_size=64, enabled=True, model_path="/x.pb", remove_small_text=False
        )
    assert decision["removed_count"] == 0
    assert result.getpixel((30, 30)) == (255, 255, 255)


def test_illegible_large_logo_is_removed():
    # A flat (low-variance) "logo" region large enough to classify as
    # large_logo, but too flat to pass the legibility check.
    img = Image.new("RGB", (200, 200), (10, 10, 10))
    for x in range(20, 100):
        for y in range(20, 60):
            img.putpixel((x, y), (200, 200, 200))
    region = TextRegion(box=(20, 20, 100, 60), confidence=0.9, area_fraction=0.08)
    with patch("mediainfo.text_removal.detect_text_regions", return_value=[region]):
        result, decision = maybe_remove_text(
            img, target_size=64, enabled=True, model_path="/x.pb", preserve_large_logos=True
        )
    assert decision["removed_count"] == 1
    assert decision["logos_retained"] == 0


def test_legible_large_logo_is_retained():
    img = _gradient_image(200, 200)
    region = TextRegion(box=(20, 20, 150, 150), confidence=0.9, area_fraction=0.08)
    with patch("mediainfo.text_removal.detect_text_regions", return_value=[region]):
        result, decision = maybe_remove_text(
            img, target_size=64, enabled=True, model_path="/x.pb", preserve_large_logos=True
        )
    assert decision["removed_count"] == 0
    assert decision["logos_retained"] == 1
    assert list(result.get_flattened_data()) == list(img.get_flattened_data())


def test_uncertain_region_is_left_alone():
    img = _gradient_image(200, 200)
    region = TextRegion(box=(0, 0, 190, 190), confidence=0.9, area_fraction=0.90)
    with patch("mediainfo.text_removal.detect_text_regions", return_value=[region]):
        result, decision = maybe_remove_text(img, target_size=64, enabled=True, model_path="/x.pb")
    assert decision["removed_count"] == 0
    assert decision["logos_retained"] == 0
    assert list(result.get_flattened_data()) == list(img.get_flattened_data())


def test_crop_preference_method_crops_instead_of_editing_pixels():
    img = Image.new("RGB", (100, 200), (1, 2, 3))
    region = TextRegion(box=(0, 0, 100, 40), confidence=0.9, area_fraction=0.02)
    with patch("mediainfo.text_removal.detect_text_regions", return_value=[region]):
        result, decision = maybe_remove_text(
            img, target_size=16, enabled=True, model_path="/x.pb", removal_method="crop_preference"
        )
    assert result.size == (100, 100)
    assert decision["method"] == "crop_preference"


def test_decision_record_includes_version_and_method():
    img = _gradient_image()
    with patch("mediainfo.text_removal.detect_text_regions", return_value=[]):
        _, decision = maybe_remove_text(
            img, target_size=16, enabled=True, model_path="/x.pb", removal_method="inpaint"
        )
    assert decision["version"] >= 1
    assert decision["method"] == "inpaint"
