"""Config dataclasses for `text_enrichers.*` plugins (see
mediainfo/enrichers/text_base.py) - lyrics/AI-generated text, as opposed
to enrichers.py's artwork enrichers.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class LrclibConfig:
    # No API key required - lrclib.net is free and public, and explicitly
    # intended for this kind of lookup/display use (crowd-sourced,
    # permissively licensed) - see mediainfo/enrichers/lrclib.py.
    enabled: bool = False


# Registry mapping config section names to their dataclass types. Adding a
# new text enricher starts here (see also registries.TEXT_ENRICHER_CLASSES).
TEXT_ENRICHER_CONFIG_TYPES: dict[str, type] = {
    "lrclib": LrclibConfig,
}
