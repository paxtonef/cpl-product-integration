"""Backups made by the delivery scripts, and their expiry.

Only what those scripts created and identified is ever deleted:

  backups            <SAUVEGARDES_DIR>/pi-sauvegarde-<AAAAMMJJTHHMMSSZ>/, made by
                     deploy/sauvegarder.sh, with its MANIFESTE (format
                     pi-sauvegarde-1) listing exactly the files present;
  pre-restore media  <PI05_MEDIA_STORAGE_DIR>.avant-restauration-<horodatage>/,
                     the media directory set aside by deploy/restaurer.sh, with
                     its MANIFESTE (format pi-avant-restauration-1).

A directory is deleted only if its name, its manifest and its exact content
match; anything else in it (another file, a sub-directory, a link, a key)
makes it "not recognised" and it is kept. The age is the creation date
written in the manifest, never a file date. The copy VIR sets aside on
restore (<VIR base>.avant-restauration-<horodatage>) belongs to VIR and is not
handled here.
"""
from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MANIFEST = "MANIFESTE"
BACKUP_FORMAT = "pi-sauvegarde-1"
PRE_RESTORE_FORMAT = "pi-avant-restauration-1"
_BACKUP_NAME = re.compile(r"^pi-sauvegarde-\d{8}T\d{6}Z$")
_MEDIA_FILE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp|heic|contenttype)$")
_BACKUP_FILES = {"postgresql.dump", "vir.db", "medias.tar", "SHA256SUMS"}
_BACKUP_OPTIONAL = {"COMPOSITION.installee"}


@dataclass
class Found:
    path: Path
    kind: str                      # "sauvegarde" | "medias_avant_restauration"
    created_at: Optional[datetime]
    recognised: bool
    reason: str = ""


def _read_manifest(directory: Path) -> Optional[dict[str, str]]:
    path = directory / MANIFEST
    if path.is_symlink() or not path.is_file():
        return None
    entries = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            entries[key.strip()] = value.strip()
    return entries


def _created(manifest: dict[str, str]) -> Optional[datetime]:
    try:
        return datetime.strptime(manifest.get("creee_le", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _plain_files(directory: Path) -> Optional[set[str]]:
    names = set()
    for entry in directory.iterdir():
        mode = entry.lstat().st_mode
        if not stat.S_ISREG(mode):
            return None
        names.add(entry.name)
    return names


def _examine_backup(directory: Path) -> Found:
    manifest = _read_manifest(directory)
    if manifest is None or manifest.get("format") != BACKUP_FORMAT:
        return Found(directory, "sauvegarde", None, False, "manifeste absent ou d'un autre format")
    created = _created(manifest)
    listed = set(manifest.get("fichiers", "").split())
    names = _plain_files(directory)
    if created is None:
        return Found(directory, "sauvegarde", None, False, "date de création illisible")
    if names is None:
        return Found(directory, "sauvegarde", created, False, "contient autre chose que des fichiers")
    if not (_BACKUP_FILES <= listed <= _BACKUP_FILES | _BACKUP_OPTIONAL) or names != listed | {MANIFEST}:
        return Found(directory, "sauvegarde", created, False, "contenu différent du manifeste")
    return Found(directory, "sauvegarde", created, True)


def _examine_pre_restore(directory: Path) -> Found:
    manifest = _read_manifest(directory)
    kind = "medias_avant_restauration"
    if manifest is None or manifest.get("format") != PRE_RESTORE_FORMAT:
        return Found(directory, kind, None, False, "manifeste absent ou d'un autre format")
    created = _created(manifest)
    names = _plain_files(directory)
    if created is None:
        return Found(directory, kind, None, False, "date de création illisible")
    if names is None or any(n != MANIFEST and not _MEDIA_FILE.match(n) for n in names):
        return Found(directory, kind, created, False, "contient autre chose que des médias")
    return Found(directory, kind, created, True)


def inventory(backup_root: Optional[Path], media_dir: Optional[Path]) -> list[Found]:
    found = []
    if backup_root is not None and backup_root.is_dir():
        for entry in sorted(backup_root.iterdir()):
            if _BACKUP_NAME.match(entry.name) and entry.is_dir() and not entry.is_symlink():
                found.append(_examine_backup(entry))
    if media_dir is not None and media_dir.parent.is_dir():
        prefix = media_dir.name + ".avant-restauration-"
        for entry in sorted(media_dir.parent.iterdir()):
            if entry.name.startswith(prefix) and entry.is_dir() and not entry.is_symlink():
                found.append(_examine_pre_restore(entry))
    return found


def due(found: list[Found], cutoff: datetime) -> list[Found]:
    return [f for f in found if f.recognised and f.created_at is not None and f.created_at < cutoff]


def delete(item: Found) -> None:
    """Deletes the recognised directory's files (re-examined just before),
    then the directory itself."""
    current = _examine_backup(item.path) if item.kind == "sauvegarde" else _examine_pre_restore(item.path)
    if not current.recognised:
        raise RuntimeError("le dossier a changé depuis l'inventaire : conservé")
    os.chmod(item.path, 0o700)
    for entry in item.path.iterdir():
        entry.unlink()
    item.path.rmdir()
