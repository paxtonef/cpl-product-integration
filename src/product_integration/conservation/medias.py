"""Uploaded media: purge by age only.

A medium is due once its upload (pi_auth.media_ownership.created_at) is past
the period. Its files ({media_id}.<ext> and {media_id}.contenttype) are
deleted; the ownership row stays, marked content_purged_at, so the reference
reads as "no longer kept". Nothing in the pixels is checked: a kept image may
show a plate or a VIN (not verifiable).

Files without an ownership row are counted, never deleted.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_MEDIA_FILE = re.compile(r"^([0-9a-f]{32})\.(jpg|png|webp|heic|contenttype)$")


def due(session: Session, cutoff: datetime) -> list[str]:
    return [row[0] for row in session.execute(text(
        "SELECT media_id FROM pi_auth.media_ownership WHERE content_purged_at IS NULL AND created_at < :c "
        "ORDER BY created_at, media_id"), {"c": cutoff})]


def orphan_files(session: Session, storage_dir: Path) -> int:
    if not storage_dir.is_dir():
        return 0
    owned = {row[0] for row in session.execute(text("SELECT media_id FROM pi_auth.media_ownership"))}
    ids = {m.group(1) for p in storage_dir.iterdir() if (m := _MEDIA_FILE.match(p.name))}
    return len(ids - owned)


def _files_of(storage_dir: Path, media_id: str) -> list[Path]:
    return [p for p in storage_dir.glob(f"{media_id}.*")
            if _MEDIA_FILE.match(p.name) and p.is_file() and not p.is_symlink()]


def purge(session: Session, storage_dir: Path, media_ids: list[str], operation_id: UUID) -> int:
    """Deletes the files first, then marks the rows (same transaction as the
    caller's batch). A failure between the two leaves rows unmarked whose
    files are gone: the next run marks them, deleting nothing more."""
    for media_id in media_ids:
        for path in _files_of(storage_dir, media_id):
            path.unlink()
    if media_ids:
        session.execute(text(
            "UPDATE pi_auth.media_ownership SET content_purged_at = now(), purge_operation_id = :o "
            "WHERE media_id = ANY(:ids) AND content_purged_at IS NULL"), {"o": operation_id, "ids": media_ids})
    return len(media_ids)


def not_kept(session: Session, media_id: str) -> bool:
    return session.execute(text(
        "SELECT 1 FROM pi_auth.media_ownership WHERE media_id = :m AND content_purged_at IS NOT NULL"),
        {"m": media_id}).first() is not None
