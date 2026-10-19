"""Rotated log files of MONTAGE_DIR.

Only files produced by rotating the assembly's own logs are considered
(pi05.log, pgdr.log, vir.log followed by a rotation suffix: ``.1``,
``.2.gz``, ``-20261019``, ``-20261019.gz``); the active logs are never
touched (their content stays until the operator's rotation). A file is due
once its last modification is past the period. Symbolic links and anything
else in the directory are left alone.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

_ROTATED = re.compile(r"^(pi05|pgdr|vir)\.log(\.\d+|-\d{8}(\d{2})?)(\.gz)?$")


def due(montage_dir: Path, cutoff: datetime) -> list[Path]:
    if not montage_dir.is_dir():
        return []
    found = []
    for path in sorted(montage_dir.iterdir()):
        if not _ROTATED.match(path.name) or path.is_symlink() or not path.is_file():
            continue
        if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
            found.append(path)
    return found


def purge(paths: list[Path]) -> int:
    for path in paths:
        path.unlink()
    return len(paths)
