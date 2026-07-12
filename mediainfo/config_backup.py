"""Timestamped backups of config.yaml, taken right before every write.

Used by the config UI's save routes and `python -m mediainfo set-password`
so a bad edit (or a save that later turns out to be wrong, even though it
passed Config.from_dict() validation) can be recovered by hand - copy the
newest file back over config.yaml and restart.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

BACKUP_DIR_NAME = ".config_backups"
DEFAULT_KEEP = 10


def list_backups(config_path: Path) -> List[Path]:
    """Backups for `config_path`, newest first."""
    backup_dir = Path(config_path).parent / BACKUP_DIR_NAME
    if not backup_dir.exists():
        return []
    return sorted(
        backup_dir.glob(f"{Path(config_path).name}.*.bak"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def backup_config_file(config_path: Path, keep: int = DEFAULT_KEEP) -> Optional[Path]:
    """Copy `config_path` into a `.config_backups` sibling directory before
    it gets overwritten, then prune down to the `keep` most recent backups.

    Returns the backup's path, or None if `config_path` doesn't exist yet
    (nothing to back up on a first-ever save).
    """
    config_path = Path(config_path)
    if not config_path.exists():
        return None

    backup_dir = config_path.parent / BACKUP_DIR_NAME
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_path = backup_dir / f"{config_path.name}.{time.strftime('%Y%m%dT%H%M%S')}.bak"
    if backup_path.exists():
        # Two backups within the same second - keep both by disambiguating.
        i = 2
        while (
            backup_dir / f"{config_path.name}.{time.strftime('%Y%m%dT%H%M%S')}-{i}.bak"
        ).exists():
            i += 1
        backup_path = backup_dir / f"{config_path.name}.{time.strftime('%Y%m%dT%H%M%S')}-{i}.bak"

    try:
        shutil.copy2(config_path, backup_path)
    except OSError:
        logger.exception(
            "Failed to back up %s before writing - proceeding without a backup", config_path
        )
        return None

    for stale in list_backups(config_path)[keep:]:
        try:
            stale.unlink()
        except OSError:
            logger.exception("Failed to prune old config backup %s", stale)

    return backup_path


def restore_backup(config_path: Path, backup_path: Path) -> None:
    """Overwrite `config_path` with the contents of `backup_path` (one of
    `list_backups(config_path)`), after first backing up whatever is
    currently there - so a restore can itself be undone.
    """
    config_path = Path(config_path)
    backup_config_file(config_path)
    shutil.copy2(backup_path, config_path)
