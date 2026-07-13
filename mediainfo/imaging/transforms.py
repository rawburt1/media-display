"""Per-output image transform pipeline.

Each transform is a small, stateless operation on a PIL Image.  A pipeline
is a list of transforms applied in order.  Pipelines are specified in the
config under each output's `transforms:` key and parsed by `parse_pipeline`.

Config format (YAML list, one entry per step):

  transforms:
    - fit: [1920, 1080]           # cover-crop to fill
    - pad: [1920, 1080]           # letterbox/pillarbox
    - pad: {width: 800, height: 480, color: white}
    - resize: [800, 600]          # exact resize
    - grayscale                   # convert to greyscale
    - blur: {radius: 2}
    - brightness: {factor: 1.2}   # >1 brighter, <1 darker
    - contrast: {factor: 1.1}
    - rotate: {degrees: 90}
    - rotate: {degrees: 90, expand: true}  # grow canvas to fit
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from typing import List

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

logger = logging.getLogger(__name__)


class Transform(ABC):
    @abstractmethod
    def apply(self, image: Image.Image) -> Image.Image: ...

    @abstractmethod
    def spec(self) -> object:
        """JSON-serialisable description — used to build the cache key."""


class Fit(Transform):
    """Scale and crop to exactly fill the target size (cover mode)."""

    def __init__(self, width: int, height: int):
        self.width = int(width)
        self.height = int(height)

    def apply(self, image: Image.Image) -> Image.Image:
        return ImageOps.fit(image.convert("RGB"), (self.width, self.height))

    def spec(self):
        return {"fit": [self.width, self.height]}


class Pad(Transform):
    """Scale to fit within bounds, pad the rest with a solid colour."""

    def __init__(self, width: int, height: int, color: str = "black"):
        self.width = int(width)
        self.height = int(height)
        self.color = color

    def apply(self, image: Image.Image) -> Image.Image:
        return ImageOps.pad(image.convert("RGB"), (self.width, self.height), color=self.color)

    def spec(self):
        return {"pad": [self.width, self.height, self.color]}


class Resize(Transform):
    """Scale to an exact size, ignoring aspect ratio."""

    def __init__(self, width: int, height: int):
        self.width = int(width)
        self.height = int(height)

    def apply(self, image: Image.Image) -> Image.Image:
        return image.convert("RGB").resize((self.width, self.height), Image.Resampling.LANCZOS)

    def spec(self):
        return {"resize": [self.width, self.height]}


class Grayscale(Transform):
    """Convert to greyscale; output is still RGB."""

    def apply(self, image: Image.Image) -> Image.Image:
        return ImageOps.grayscale(image).convert("RGB")

    def spec(self):
        return {"grayscale": True}


class Blur(Transform):
    def __init__(self, radius: float = 2.0):
        self.radius = float(radius)

    def apply(self, image: Image.Image) -> Image.Image:
        return image.filter(ImageFilter.GaussianBlur(self.radius))

    def spec(self):
        return {"blur": self.radius}


class Brightness(Transform):
    """Multiply brightness by factor (1.0 = unchanged, >1 = brighter)."""

    def __init__(self, factor: float):
        self.factor = float(factor)

    def apply(self, image: Image.Image) -> Image.Image:
        return ImageEnhance.Brightness(image).enhance(self.factor)

    def spec(self):
        return {"brightness": self.factor}


class Contrast(Transform):
    """Adjust contrast by factor (1.0 = unchanged, >1 = more contrast)."""

    def __init__(self, factor: float):
        self.factor = float(factor)

    def apply(self, image: Image.Image) -> Image.Image:
        return ImageEnhance.Contrast(image).enhance(self.factor)

    def spec(self):
        return {"contrast": self.factor}


class Rotate(Transform):
    """Rotate clockwise by degrees.  expand=True grows canvas to avoid clipping."""

    def __init__(self, degrees: float, expand: bool = False):
        self.degrees = float(degrees)
        self.expand = bool(expand)

    def apply(self, image: Image.Image) -> Image.Image:
        return image.rotate(-self.degrees, expand=self.expand)

    def spec(self):
        return {"rotate": {"degrees": self.degrees, "expand": self.expand}}


_REGISTRY: dict[str, type] = {
    "fit": Fit,
    "pad": Pad,
    "resize": Resize,
    "grayscale": Grayscale,
    "blur": Blur,
    "brightness": Brightness,
    "contrast": Contrast,
    "rotate": Rotate,
}


def parse_pipeline(raw: list) -> List[Transform]:
    """Parse the YAML list from config into a list of Transform objects.

    Each YAML entry may be:
      "grayscale"                          → Grayscale()
      {fit: [1920, 1080]}                  → Fit(1920, 1080)
      {pad: {width: 800, height: 480}}     → Pad(800, 480)
      {brightness: 1.2}                    → Brightness(1.2)
    """
    result: List[Transform] = []
    for entry in raw or []:
        if isinstance(entry, str):
            name, params = entry, None
        elif isinstance(entry, dict):
            name, params = next(iter(entry.items()))
        else:
            logger.warning("Ignoring unrecognised transform entry: %r", entry)
            continue

        cls = _REGISTRY.get(name)
        if cls is None:
            logger.warning("Unknown transform %r — skipping", name)
            continue

        try:
            if params is None:
                result.append(cls())
            elif isinstance(params, list):
                result.append(cls(*params))
            elif isinstance(params, dict):
                result.append(cls(**params))
            else:
                result.append(cls(params))  # single scalar, e.g. brightness: 1.2
        except TypeError as exc:
            logger.warning("Bad params for transform %r: %s — skipping", name, exc)

    return result


def pipeline_cache_key(transforms: List[Transform]) -> str:
    """Stable 16-char hex hash of a pipeline, used to derive the cache filename."""
    specs = [t.spec() for t in transforms]
    return hashlib.sha256(json.dumps(specs, sort_keys=True).encode()).hexdigest()[:16]
