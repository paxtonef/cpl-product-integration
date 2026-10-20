"""Backups made by the delivery scripts, and their expiry.

Only what those scripts created and identified is ever deleted:

  backups            <SAUVEGARDES_DIR>/pi-sauvegarde-<AAAAMMJJTHHMMSSZ>/, made by
                     deploy/sauvegarder.sh, with its MANIFESTE (format
                     pi-sauvegarde-1) listing exactly the files present;
  pre-restore media  <PI05_MEDIA_STORAGE_DIR>.avant-restauration-<horodatage>/,
                     the media directory set aside by deploy/restaurer.sh, with
                     its MANIFESTE (format pi-avant-restauration-1);
  pre-restore VIR    <VIR_DATABASE_PATH>.avant-restauration-<horodatage>, the
                     file VIR's own restore command copies aside (0600, VIR's
                     encrypted records), recognised only with the manifest
                     deploy/restaurer.sh writes beside it
                     (<copy>.MANIFESTE, format pi-copie-vir-1: name, size and
                     SHA-256 of the copy). VIR's code is not changed.

A directory or copy is deleted only if its name, its manifest and its exact
content match; anything else (another file, a sub-directory, a link, a key,
a VIR copy without its manifest or whose digest differs) is "not
recognised": reported, never deleted. The age is the creation date written
in the manifest, never a file date. deploy/restaurer.sh sets no PostgreSQL
copy aside (it replaces the base in place).
"""
from __future__ import annotations

import hashlib
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
VIR_COPY_FORMAT = "pi-copie-vir-1"
VIR_COPY_MANIFEST_SUFFIX = ".MANIFESTE"
KINDS = {"sauvegarde": "sauvegardes (deploy/sauvegarder.sh)",
         "medias_avant_restauration": "médias mis de côté par une restauration",
         "vir_avant_restauration": "copie de la base VIR mise de côté par une restauration"}
_BACKUP_NAME = re.compile(r"^pi-sauvegarde-\d{8}T\d{6}Z$")
_MEDIA_FILE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp|heic|contenttype)$")
_BACKUP_FILES = {"postgresql.dump", "vir.db", "medias.tar", "SHA256SUMS"}
_BACKUP_OPTIONAL = {"COMPOSITION.installee"}


@dataclass
class Found:
    path: Path
    kind: str                      # a key of KINDS
    created_at: Optional[datetime]
    recognised: bool
    reason: str = ""


def _read_manifest(directory: Path, path: Optional[Path] = None) -> Optional[dict[str, str]]:
    path = path or directory / MANIFEST
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _examine_vir_copy(path: Path) -> Found:
    kind = "vir_avant_restauration"
    manifest = _read_manifest(path.parent, path.with_name(path.name + VIR_COPY_MANIFEST_SUFFIX))
    if manifest is None or manifest.get("format") != VIR_COPY_FORMAT or manifest.get("fichier") != path.name:
        return Found(path, kind, None, False, "copie VIR sans manifeste de deploy/restaurer.sh")
    created = _created(manifest)
    if created is None:
        return Found(path, kind, None, False, "date de création illisible")
    if not stat.S_ISREG(path.lstat().st_mode) or str(path.stat().st_size) != manifest.get("taille") \
            or _sha256(path) != manifest.get("sha256"):
        return Found(path, kind, created, False, "copie différente de son manifeste")
    return Found(path, kind, created, True)


def inventory(backup_root: Optional[Path], media_dir: Optional[Path],
              vir_database: Optional[Path] = None) -> list[Found]:
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
    if vir_database is not None and vir_database.parent.is_dir():
        name = re.compile(re.escape(vir_database.name) + r"\.avant-restauration-\d{8}T\d{6}Z$")
        for entry in sorted(vir_database.parent.iterdir()):
            if name.match(entry.name) and not entry.is_dir():
                found.append(_examine_vir_copy(entry))
    return found


def due(found: list[Found], cutoff: datetime) -> list[Found]:
    return [f for f in found if f.recognised and f.created_at is not None and f.created_at < cutoff]


def delete(item: Found) -> None:
    """Deletes the recognised directory's files (re-examined just before),
    then the directory itself."""
    examine = {"sauvegarde": _examine_backup, "medias_avant_restauration": _examine_pre_restore,
               "vir_avant_restauration": _examine_vir_copy}[item.kind]
    if not examine(item.path).recognised:
        raise RuntimeError("le dossier a changé depuis l'inventaire : conservé")
    if item.kind == "vir_avant_restauration":
        item.path.unlink()
        item.path.with_name(item.path.name + VIR_COPY_MANIFEST_SUFFIX).unlink()
        return
    os.chmod(item.path, 0o700)
    for entry in item.path.iterdir():
        entry.unlink()
    item.path.rmdir()
