"""Optional text-detection + removal stage for the Pixoo LED pipeline (see
mediainfo/led_image.py, which runs after this module - crop/enhance/
downsample/quantize all happen on whatever image this stage produces).

Small poster typography (credits, subtitles, track listings) survives
crop+downscale+quantize as unreadable noise at 16x16/64x64. This module
finds text-like regions with OpenCV's EAST detector (a pretrained neural
net - see PixooConfig.text_detection_model_path, which must point at a
locally-provided `frozen_east_text_detection.pb`; this module never
downloads one itself) and either removes small/illegible text or keeps
large, still-legible logos/titles.

Classification is by region size/position only, not by reading the text
(no OCR) - "is this a small credits line or a large title" doesn't need to
know what the text actually says.

Optional at every level: if OpenCV isn't installed, or `model_path` is
empty/unloadable, detection returns no regions and the image passes
through unchanged - this stage is always a no-op by default
(PixooConfig.text_detection_enabled defaults to False).
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Callable, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageStat

logger = logging.getLogger(__name__)

# Bump when this module's detection/classification/removal logic changes in
# a way that should invalidate previously cached decisions/derivatives.
_TEXT_REMOVAL_VERSION = 1

# EAST requires input dimensions that are multiples of 32.
_EAST_INPUT_SIZE = 320
_EAST_MEAN = (123.68, 116.78, 103.94)
_EAST_LAYER_NAMES = ("feature_fusion/Conv_7/Sigmoid", "feature_fusion/concat_3")

# Below this fraction of the image's area, a detected region is "small" -
# typical credits/subtitle text, always a removal candidate.
_SMALL_TEXT_MAX_AREA_FRACTION = 0.02

# A logo/title candidate that would render smaller than this many pixels
# (either dimension) at the final LED size, or whose downscaled content is
# this flat, is considered illegible and treated the same as small text.
_MIN_LEGIBLE_PIXELS = 3
_MIN_LEGIBLE_STDDEV = 12.0

_cv2_warned = False


@dataclasses.dataclass
class TextRegion:
    box: Tuple[int, int, int, int]  # (x1, y1, x2, y2) in original image coords
    confidence: float
    area_fraction: float
    classification: str = "uncertain"  # "small" | "large_logo" | "uncertain"


def _import_cv2() -> Any:
    global _cv2_warned
    try:
        import cv2

        return cv2
    except ImportError:
        if not _cv2_warned:
            logger.warning(
                "Pixoo text detection is enabled but opencv-python-headless "
                "is not installed - skipping the text-removal stage."
            )
            _cv2_warned = True
        return None


def detect_text_regions(
    image: Image.Image,
    model_path: str,
    confidence_threshold: float = 0.5,
    nms_threshold: float = 0.4,
    net_loader: Optional[Callable[[str], Any]] = None,
) -> List[TextRegion]:
    """Detect text-like regions using OpenCV's EAST text detector.

    Returns [] (never raises) if OpenCV isn't installed, `model_path` is
    empty, or the model fails to load - detection is always an optional
    enhancement. `net_loader` (model_path -> a cv2.dnn Net-like object with
    setInput()/forward()) is injectable so tests can exercise the decode
    logic below without a real model file.
    """
    if not model_path:
        return []
    cv2 = _import_cv2()
    if cv2 is None:
        return []

    loader = net_loader or (lambda path: cv2.dnn.readNet(path))
    try:
        net = loader(model_path)
    except Exception:
        logger.warning("Could not load text-detection model at %s", model_path, exc_info=True)
        return []
    if net is None:
        return []

    import numpy as np

    orig_w, orig_h = image.size
    new_w = new_h = _EAST_INPUT_SIZE
    ratio_w = orig_w / new_w
    ratio_h = orig_h / new_h

    resized = image.convert("RGB").resize((new_w, new_h), Image.Resampling.BILINEAR)
    bgr = np.array(resized)[:, :, ::-1]
    blob = cv2.dnn.blobFromImage(bgr, 1.0, (new_w, new_h), _EAST_MEAN, swapRB=False, crop=False)
    net.setInput(blob)
    scores, geometry = net.forward(list(_EAST_LAYER_NAMES))

    boxes, confidences = _decode_predictions(scores, geometry, confidence_threshold, np)
    if not boxes:
        return []

    xywh = [(x1, y1, x2 - x1, y2 - y1) for (x1, y1, x2, y2) in boxes]
    indices = cv2.dnn.NMSBoxes(xywh, confidences, confidence_threshold, nms_threshold)
    indices = np.array(indices).flatten() if len(indices) else []
    if len(indices) == 0:
        return []

    total_area = float(orig_w * orig_h)
    regions = []
    for i in indices:
        x1, y1, x2, y2 = boxes[i]
        ox1 = max(0, int(x1 * ratio_w))
        oy1 = max(0, int(y1 * ratio_h))
        ox2 = min(orig_w, int(x2 * ratio_w))
        oy2 = min(orig_h, int(y2 * ratio_h))
        if ox2 <= ox1 or oy2 <= oy1:
            continue
        area_fraction = ((ox2 - ox1) * (oy2 - oy1)) / total_area
        regions.append(TextRegion(box=(ox1, oy1, ox2, oy2), confidence=float(confidences[i]), area_fraction=area_fraction))
    return regions


def _decode_predictions(scores: Any, geometry: Any, confidence_threshold: float, np: Any) -> Tuple[list, list]:
    """Standard EAST geometry decode: for each grid cell above the
    confidence threshold, reconstruct its (unrotated) bounding box from the
    4 distance-to-edge maps and the rotation-angle map. Rotation is decoded
    (needed to place the box correctly) but the result is stored as an
    axis-aligned box - good enough for building a removal mask and judging
    region size, which is all this module needs.
    """
    num_rows, num_cols = scores.shape[2:4]
    boxes = []
    confidences = []
    for y in range(num_rows):
        scores_row = scores[0, 0, y]
        x0 = geometry[0, 0, y]
        x1 = geometry[0, 1, y]
        x2 = geometry[0, 2, y]
        x3 = geometry[0, 3, y]
        angles = geometry[0, 4, y]
        for x in range(num_cols):
            score = scores_row[x]
            if score < confidence_threshold:
                continue
            offset_x, offset_y = x * 4.0, y * 4.0
            angle = angles[x]
            cos, sin = np.cos(angle), np.sin(angle)
            box_h = x0[x] + x2[x]
            box_w = x1[x] + x3[x]
            end_x = int(offset_x + (cos * x1[x]) + (sin * x2[x]))
            end_y = int(offset_y - (sin * x1[x]) + (cos * x2[x]))
            start_x = int(end_x - box_w)
            start_y = int(end_y - box_h)
            boxes.append((start_x, start_y, end_x, end_y))
            confidences.append(float(score))
    return boxes, confidences


def classify_regions(regions: List[TextRegion], max_logo_area_percent: float) -> List[TextRegion]:
    """Classify by area fraction alone:
      - "small": under 2% of the image - typical credits/subtitle text.
      - "large_logo": between 2% and max_logo_area_percent% - a plausible
        title/logo candidate (still subject to the legibility check in
        maybe_remove_text before it's actually retained).
      - "uncertain": above max_logo_area_percent% - too large to be a
        normal logo (more likely a misdetection over a big background
        area); left alone rather than edited, since removing something
        covering that much of the frame risks damaging the composition.
    """
    max_fraction = max_logo_area_percent / 100.0
    classified = []
    for r in regions:
        if r.area_fraction >= max_fraction:
            classification = "uncertain"
        elif r.area_fraction >= _SMALL_TEXT_MAX_AREA_FRACTION:
            classification = "large_logo"
        else:
            classification = "small"
        classified.append(dataclasses.replace(r, classification=classification))
    return classified


def _legible_at_target_size(image: Image.Image, box: Tuple[int, int, int, int], target_size: int) -> bool:
    """Conservative proxy for "would this logo/title still read as
    something at the final LED resolution": scales the cropped region down
    by the same ratio the whole image will eventually be downscaled by,
    and rejects it if that leaves too few pixels or a near-flat blob (no
    structure left to recognise).
    """
    x1, y1, x2, y2 = box
    w, h = image.size
    scale = target_size / min(w, h)
    scaled_w = max(1, round((x2 - x1) * scale))
    scaled_h = max(1, round((y2 - y1) * scale))
    if scaled_w < _MIN_LEGIBLE_PIXELS or scaled_h < _MIN_LEGIBLE_PIXELS:
        return False
    region = image.crop(box).convert("L").resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
    return ImageStat.Stat(region).stddev[0] >= _MIN_LEGIBLE_STDDEV


def _expand_box(box: Tuple[int, int, int, int], margin_ratio: float, w: int, h: int) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    mx = max(2, int((x2 - x1) * margin_ratio))
    my = max(2, int((y2 - y1) * margin_ratio))
    return (max(0, x1 - mx), max(0, y1 - my), min(w, x2 + mx), min(h, y2 + my))


def _build_mask(image: Image.Image, regions: List[TextRegion], margin_ratio: float) -> Image.Image:
    w, h = image.size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    for r in regions:
        draw.rectangle(_expand_box(r.box, margin_ratio, w, h), fill=255)
    return mask


def _inpaint_remove(image: Image.Image, regions: List[TextRegion], margin_ratio: float) -> Optional[Image.Image]:
    cv2 = _import_cv2()
    if cv2 is None:
        return None
    import numpy as np

    mask = _build_mask(image, regions, margin_ratio)
    bgr = np.array(image.convert("RGB"))[:, :, ::-1].copy()
    result_bgr = cv2.inpaint(bgr, np.array(mask), 3, cv2.INPAINT_TELEA)
    return Image.fromarray(result_bgr[:, :, ::-1])


def _soft_fill_remove(image: Image.Image, regions: List[TextRegion], margin_ratio: float) -> Image.Image:
    w, h = image.size
    mask = _build_mask(image, regions, margin_ratio)
    blur_radius = max(4, min(w, h) // 8)
    blurred = image.filter(ImageFilter.GaussianBlur(blur_radius))
    soft_mask = mask.filter(ImageFilter.GaussianBlur(max(1, blur_radius // 2)))
    return Image.composite(blurred, image, soft_mask)


def remove_text(
    image: Image.Image, regions: List[TextRegion], method: str = "inpaint", margin_ratio: float = 0.15
) -> Image.Image:
    """Erase `regions` from `image` (mask expanded by `margin_ratio` to
    also cover outlines/shadows/glow around the text itself). Falls back
    to the soft-fill reconstruction if `method` is "inpaint" but OpenCV
    isn't available - never leaves sharp text fragments unhandled.
    """
    if not regions:
        return image
    if method == "inpaint":
        result = _inpaint_remove(image, regions, margin_ratio)
        if result is not None:
            return result
    return _soft_fill_remove(image, regions, margin_ratio)


def _overlap_area(box: Tuple[int, int, int, int], avoid_boxes: List[Tuple[int, int, int, int]]) -> int:
    x1, y1, x2, y2 = box
    total = 0
    for ax1, ay1, ax2, ay2 in avoid_boxes:
        ix1, iy1 = max(x1, ax1), max(y1, ay1)
        ix2, iy2 = min(x2, ax2), min(y2, ay2)
        if ix2 > ix1 and iy2 > iy1:
            total += (ix2 - ix1) * (iy2 - iy1)
    return total


def _crop_avoiding_regions(
    image: Image.Image, crop_strategy: str, avoid_boxes: List[Tuple[int, int, int, int]]
) -> Image.Image:
    """Used by the "crop_preference" removal method: instead of editing
    pixels, pick whichever square crop (among a handful of candidate
    offsets along the axis crop_strategy has slack on) overlaps the least
    with `avoid_boxes`. A no-op (falls back to the normal crop_strategy
    behaviour) for square images, which have no slack to work with.
    """
    from mediainfo.led_image import _crop_square

    w, h = image.size
    if w == h or not avoid_boxes:
        return _crop_square(image, crop_strategy)

    s = min(w, h)
    if h > w:
        slack = h - s
        fixed = (w - s) // 2

        def box_for(offset: int) -> Tuple[int, int, int, int]:
            return (fixed, offset, fixed + s, offset + s)
    else:
        slack = w - s
        fixed = (h - s) // 2

        def box_for(offset: int) -> Tuple[int, int, int, int]:
            return (offset, fixed, offset + s, fixed + s)

    candidates = sorted({0, slack // 4, slack // 2, (slack * 3) // 4, slack})
    best_offset, best_overlap = slack // 2, None
    for offset in candidates:
        overlap = _overlap_area(box_for(offset), avoid_boxes)
        if best_overlap is None or overlap < best_overlap:
            best_overlap, best_offset = overlap, offset

    return image.crop(box_for(best_offset))


def maybe_remove_text(
    image: Image.Image,
    target_size: int,
    enabled: bool = False,
    model_path: str = "",
    remove_small_text: bool = True,
    preserve_large_logos: bool = True,
    removal_method: str = "inpaint",
    max_logo_area_percent: float = 25.0,
    crop_strategy: str = "automatic",
    net_loader: Optional[Callable[[str], Any]] = None,
) -> Tuple[Image.Image, Optional[dict]]:
    """Top-level entry point: detect, classify, and act on text regions
    before the rest of the LED pipeline runs. Returns (possibly-modified
    image, decision record) - the record is None when disabled (nothing to
    persist), and otherwise mirrors what's written as the cache
    derivative's metadata sidecar (see ImageCache.get_derived_path).
    """
    if not enabled:
        return image, None

    regions = detect_text_regions(image, model_path, net_loader=net_loader)
    classified = classify_regions(regions, max_logo_area_percent)

    if removal_method == "crop_preference":
        avoid = []
        retained_logos = 0
        for r in classified:
            if r.classification == "small":
                if remove_small_text:
                    avoid.append(r.box)
            elif r.classification == "large_logo":
                if preserve_large_logos and _legible_at_target_size(image, r.box, target_size):
                    retained_logos += 1
                else:
                    avoid.append(r.box)
        processed = _crop_avoiding_regions(image, crop_strategy, avoid)
        removed_count = len(avoid)
    else:
        to_remove = []
        retained_logos = 0
        for r in classified:
            if r.classification == "small":
                if remove_small_text:
                    to_remove.append(r)
            elif r.classification == "large_logo":
                if preserve_large_logos and _legible_at_target_size(image, r.box, target_size):
                    retained_logos += 1
                else:
                    to_remove.append(r)
        processed = remove_text(image, to_remove, method=removal_method) if to_remove else image
        removed_count = len(to_remove)

    decision = {
        "version": _TEXT_REMOVAL_VERSION,
        "regions": [dataclasses.asdict(r) for r in classified],
        "removed_count": removed_count,
        "logos_retained": retained_logos,
        "method": removal_method,
    }
    return processed, decision
