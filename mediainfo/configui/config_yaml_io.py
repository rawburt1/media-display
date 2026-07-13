"""Comment-preserving YAML read/dump helpers for config.yaml, shared by
config_ui.py's config store and Apple TV pairing (both need to read-modify-
write the same file). Split out of config_ui.py since it's used by more
than one of its extracted collaborators.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True


def _read_config(path: Path) -> Any:
    if not path.exists():
        return _yaml.map()
    with path.open("r", encoding="utf-8") as f:
        return _yaml.load(f) or _yaml.map()


def _dump_config(data: Any) -> str:
    buf = io.StringIO()
    _yaml.dump(data, buf)
    return buf.getvalue()
