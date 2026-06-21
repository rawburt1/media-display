"""Shared image-transition CSS/JS for outputs that cross-fade between two
absolutely-positioned <img> elements (web, info, video).

Each image change picks a random variant - plain fade, a slide in from one
of the four sides, or a subtle zoom - so the display doesn't always use the
same effect. Any variant can be excluded per-output via config (e.g.
`transition_exclude: [slide-left, slide-right]`), in case a particular
panel looks bad with motion. Excluding all of them falls back to fade
rather than leaving the image with no transition at all.
"""

from __future__ import annotations

import json
from typing import List

ALL_TRANSITIONS = ["fade", "slide-left", "slide-right", "slide-up", "slide-down", "zoom"]


def transitions_css(container_selector: str = "#art-container") -> str:
    """CSS for the variant classes JS applies to the standby <img> before
    loading it - `container_selector` is the id of the element wrapping the
    two <img>s, since different outputs name it differently.
    """
    c = container_selector
    return f"""
    {c} img.t-slide-left  {{ transform: translateX(6%); }}
    {c} img.t-slide-right {{ transform: translateX(-6%); }}
    {c} img.t-slide-up    {{ transform: translateY(6%); }}
    {c} img.t-slide-down  {{ transform: translateY(-6%); }}
    {c} img.t-zoom        {{ transform: scale(1.12); }}
    {c} img.visible       {{ opacity: 1; transform: translate(0, 0) scale(1); }}
"""


def transitions_js(exclude: List[str]) -> str:
    """JS defining `prepareForTransition(img)`, which the caller invokes on
    the standby <img> right before assigning its new `src` - it clears any
    previous variant class and applies a freshly (randomly) picked one, so
    the image's entrance transition is set up before the browser starts
    loading it.
    """
    all_classes = [f"t-{name}" for name in ALL_TRANSITIONS]
    variants = [cls for name, cls in zip(ALL_TRANSITIONS, all_classes) if name not in exclude]
    if not variants:
        variants = ["t-fade"]

    return f"""
    const ALL_TRANSITION_CLASSES = {json.dumps(all_classes)};
    const TRANSITION_VARIANTS = {json.dumps(variants)};

    function prepareForTransition(img) {{
      img.classList.remove("visible", ...ALL_TRANSITION_CLASSES);
      img.classList.add(TRANSITION_VARIANTS[Math.floor(Math.random() * TRANSITION_VARIANTS.length)]);
    }}
    """
