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


@dataclasses.dataclass
class MediaDataLyricsEnricherConfig:
    # Checks the local unified media-data cache (see
    # mediainfo/media_data_store.py, configured via the top-level
    # `mediadata:` section) for track lyrics - see mediainfo/enrichers/
    # mediadata_lyrics.py. No credentials of its own; a cache miss falls
    # through to a real LRCLIB (free) lookup.
    enabled: bool = False


@dataclasses.dataclass
class OllamaTextConfig:
    # Off by default - requires a local Ollama instance the user has set
    # up (and pulled a model into) themselves; see
    # mediainfo/enrichers/ollama_text.py.
    enabled: bool = False
    host: str = "localhost"
    port: int = 11434
    # Must already be pulled in Ollama (e.g. `ollama pull llama3.2`) -
    # this enricher doesn't pull/manage models itself.
    model: str = "llama3.2"
    # Local inference can be slow depending on model size/hardware; this
    # bounds how long one enrichment call may block the orchestrator's
    # tick loop before giving up (see the enricher's module docstring).
    timeout_seconds: int = 30


# Registry mapping config section names to their dataclass types. Adding a
# new text enricher starts here (see also registries.TEXT_ENRICHER_CLASSES).
TEXT_ENRICHER_CONFIG_TYPES: dict[str, type] = {
    "lrclib": LrclibConfig,
    "mediadata": MediaDataLyricsEnricherConfig,
    "ollama_text": OllamaTextConfig,
}
