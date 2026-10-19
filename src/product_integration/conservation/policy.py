"""Explicit conservation policy, one setting per category, read from the
environment. No default duration exists and none is inferred: an absent
setting is "not defined", never a number. VIR's own VIR_RETENTION_DAYS
governs VIR's store only and is never taken for any category here.

Value of each setting: a whole number of days (1 or more; a day is 24 hours,
counted in UTC from the category's starting point below), or ``illimitee``
for a conservation explicitly chosen without limit.

Starting points (one implemented per category, named here):
  identifiers   ``enregistrement_cpl``: when the identification record that
                holds the copy was written in CPL (created_at of the
                resolution). A driver confirmation, correction or withdrawal
                writes a new record, which starts its own period. Other
                candidates (last driver confirmation of the case, last
                consultation) are not implemented: the choice is the owner's.
  cases         when the case was created (no deletion mechanism exists, see
                purge.py: only ``illimitee`` can be executed).
  media         ``envoi``: when the medium was uploaded (media_ownership).
  logs          last modification of a rotated log file.
  backups       creation date written in the backup's manifest.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

UNLIMITED = "illimitee"


@dataclass(frozen=True)
class Category:
    key: str
    env: str
    label: str
    anchor: str


IDENTIFIERS = Category("identifiants", "PI_CONSERVATION_IDENTIFIANTS_JOURS",
                       "plaque et VIN et leurs copies dans CPL", "enregistrement_cpl")
CASES = Category("dossiers", "PI_CONSERVATION_DOSSIERS_JOURS",
                 "dossiers et résultats", "creation_dossier")
MEDIA = Category("medias", "PI_CONSERVATION_MEDIAS_JOURS", "médias envoyés", "envoi")
LOGS = Category("journaux", "PI_CONSERVATION_JOURNAUX_JOURS",
                "journaux tournés de MONTAGE_DIR", "derniere_modification_fichier")
BACKUPS = Category("sauvegardes", "PI_CONSERVATION_SAUVEGARDES_JOURS",
                   "sauvegardes des scripts de livraison", "creation_manifeste")

ALL = (IDENTIFIERS, CASES, MEDIA, LOGS, BACKUPS)
PURGE_CATEGORIES = (IDENTIFIERS, CASES, MEDIA, LOGS)


class PolicyError(ValueError):
    """A setting is present but not a valid policy value."""


@dataclass(frozen=True)
class Setting:
    category: Category
    days: Optional[int]          # None: unlimited or undefined
    defined: bool

    @property
    def unlimited(self) -> bool:
        return self.defined and self.days is None

    def describe(self) -> str:
        if not self.defined:
            return "non définie"
        if self.unlimited:
            return "illimitée (choix explicite)"
        return f"{self.days} jour(s) depuis {self.category.anchor}"

    def as_json(self) -> dict:
        return {"defined": self.defined, "days": self.days, "unlimited": self.unlimited,
                "anchor": self.category.anchor, "env": self.category.env}


def read_setting(category: Category, environ=None) -> Setting:
    raw = (environ if environ is not None else os.environ).get(category.env, "").strip()
    if raw == "":
        return Setting(category, None, False)
    if raw == UNLIMITED:
        return Setting(category, None, True)
    if not raw.isdigit() or int(raw) < 1:
        raise PolicyError(f"{category.env} : nombre entier de jours (1 ou plus) ou « {UNLIMITED} » attendu")
    return Setting(category, int(raw), True)


def read_policy(environ=None) -> dict[str, Setting]:
    return {c.key: read_setting(c, environ) for c in ALL}
