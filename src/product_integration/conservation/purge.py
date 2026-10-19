"""The purge: simulation (default) and execution, category by category.

Simulation reads only and works without any policy ("aucune politique, rien
ne serait supprimé"). Execution refuses before any write unless every
category it covers has an explicit policy (policy.py), and refuses a
numeric period for cases and results: CPL provides no deletion of a case,
its executions or its artifacts (append-only history, FK RESTRICT,
REQ-B6-058), so only ``illimitee`` can be honoured for them.

Execution works in batches, each in its own transaction, and records the
operation in pi_auth.conservation_operations (policy, counts, outcome; never
a purged value). On an error the current batch is rolled back, the
operation is marked interrupted with the error's class only, and the error
is raised again; a new run takes up what is left (anything already emptied
or purged is not counted again).
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text

from app.db.engine import session_scope

from product_integration.conservation import identifiants, journaux, medias
from product_integration.conservation.policy import (
    CASES, IDENTIFIERS, LOGS, MEDIA, PURGE_CATEGORIES, Setting, read_policy,
)

DEFAULT_BATCH = 200
NO_POLICY = "aucune politique, rien ne serait supprimé"


class PurgeRefused(Exception):
    """Execution refused before any write."""


@dataclass
class Line:
    key: str
    label: str
    policy: str
    detail: str


@dataclass
class Report:
    executed: bool
    lines: list[Line] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    operation_id: Optional[uuid.UUID] = None

    def render(self) -> str:
        head = "Conservation — exécution" if self.executed else "Conservation — simulation (rien n'est modifié)"
        body = [f"- {l.key} ({l.label}) — politique : {l.policy} — {l.detail}" for l in self.lines]
        tail = [f"Opération : {self.operation_id}"] if self.operation_id else []
        return "\n".join([head, *body, *tail])


def _cutoff(setting: Setting, now: datetime) -> Optional[datetime]:
    return None if setting.days is None else now - timedelta(days=setting.days)


def _media_dir(environ) -> Optional[Path]:
    value = environ.get("PI05_MEDIA_STORAGE_DIR")
    return Path(value) if value else None


def _montage_dir(environ) -> Optional[Path]:
    value = environ.get("MONTAGE_DIR")
    return Path(value) if value else None


def refusal_reasons(policy: dict[str, Setting]) -> list[str]:
    reasons = []
    missing = [policy[c.key].category.env for c in PURGE_CATEGORIES if not policy[c.key].defined]
    if missing:
        reasons.append("politique non définie : " + ", ".join(missing))
    if policy[CASES.key].days is not None:
        reasons.append(f"{CASES.env} : aucune suppression de dossier n'existe (CPL conserve dossiers, exécutions et "
                       f"artefacts) ; seule la valeur « illimitee » peut être appliquée")
    return reasons


def simulate(environ=None, now: Optional[datetime] = None) -> Report:
    environ = os.environ if environ is None else environ
    now = now or datetime.now(timezone.utc)
    policy = read_policy(environ)
    report = Report(executed=False)
    with session_scope() as session:
        s = policy[IDENTIFIERS.key]
        if not s.defined:
            report.lines.append(Line(IDENTIFIERS.key, IDENTIFIERS.label, s.describe(), NO_POLICY))
        elif s.unlimited:
            report.lines.append(Line(IDENTIFIERS.key, IDENTIFIERS.label, s.describe(), "rien ne serait supprimé"))
        else:
            p = identifiants.plan(session, _cutoff(s, now))
            report.counts.update(resolutions=len(p.resolutions), vehicle_details=len(p.vehicle_details),
                                 artifacts_blocked=p.artifacts_blocked)
            report.lines.append(Line(IDENTIFIERS.key, IDENTIFIERS.label, s.describe(),
                f"{len(p.resolutions)} résolution(s) d'identité et {len(p.vehicle_details)} fiche(s) véhicule seraient "
                f"vidées de plaque et VIN ; {p.artifacts_blocked} artefact(s) vir_resolution échu(s) les garderaient "
                f"(expurgation impossible sans évolution de CPL)"))

        s = policy[CASES.key]
        detail = NO_POLICY if not s.defined else (
            "rien ne serait supprimé" if s.unlimited else
            "exécution refusée : aucune suppression de dossier n'existe dans CPL ; rien ne serait supprimé")
        report.lines.append(Line(CASES.key, CASES.label, s.describe(), detail))

        s = policy[MEDIA.key]
        media_dir = _media_dir(environ)
        if not s.defined or s.unlimited:
            report.lines.append(Line(MEDIA.key, MEDIA.label, s.describe(),
                                     NO_POLICY if not s.defined else "rien ne serait supprimé"))
        else:
            due = medias.due(session, _cutoff(s, now))
            orphans = medias.orphan_files(session, media_dir) if media_dir else 0
            report.counts.update(media=len(due), media_orphans=orphans)
            report.lines.append(Line(MEDIA.key, MEDIA.label, s.describe(),
                f"{len(due)} média(s) seraient supprimés ; {orphans} fichier(s) sans propriétaire, non traités"))

    s = policy[LOGS.key]
    montage_dir = _montage_dir(environ)
    if not s.defined or s.unlimited:
        report.lines.append(Line(LOGS.key, LOGS.label, s.describe(),
                                 NO_POLICY if not s.defined else "rien ne serait supprimé"))
    else:
        due_logs = journaux.due(montage_dir, _cutoff(s, now)) if montage_dir else []
        report.counts["logs"] = len(due_logs)
        report.lines.append(Line(LOGS.key, LOGS.label, s.describe(),
            f"{len(due_logs)} journal(aux) tourné(s) seraient supprimés" if montage_dir
            else "MONTAGE_DIR absent : aucun journal examiné"))
    return report


def _start_operation(policy: dict[str, Setting], trigger: str) -> uuid.UUID:
    operation_id = uuid.uuid4()
    with session_scope() as session:
        session.execute(text(
            "INSERT INTO pi_auth.conservation_operations(operation_id, trigger, policy, outcome) "
            "VALUES (:o, :t, CAST(:p AS jsonb), 'running')"),
            {"o": operation_id, "t": trigger, "p": json.dumps({k: v.as_json() for k, v in policy.items()})})
        session.commit()
    return operation_id


def _finish_operation(operation_id: uuid.UUID, counts: dict, outcome: str, error_class: Optional[str] = None) -> None:
    with session_scope() as session:
        session.execute(text(
            "UPDATE pi_auth.conservation_operations SET finished_at = now(), counts = CAST(:c AS jsonb), "
            "outcome = :r, error_class = :e WHERE operation_id = :o"),
            {"o": operation_id, "c": json.dumps(counts), "r": outcome, "e": error_class})
        session.commit()


def _batches(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def execute(environ=None, now: Optional[datetime] = None, trigger: str = "operator",
            batch_size: int = DEFAULT_BATCH) -> Report:
    environ = os.environ if environ is None else environ
    now = now or datetime.now(timezone.utc)
    policy = read_policy(environ)
    reasons = refusal_reasons(policy)
    if reasons:
        raise PurgeRefused("Exécution refusée, rien n'est supprimé : " + " ; ".join(reasons))

    operation_id = _start_operation(policy, trigger)
    counts = {"resolutions": 0, "vehicle_details": 0, "artifacts_blocked": 0, "media": 0, "logs": 0}
    report = Report(executed=True, operation_id=operation_id, counts=counts)
    try:
        s = policy[IDENTIFIERS.key]
        if s.days is not None:
            cutoff = _cutoff(s, now)
            with session_scope() as session:
                p = identifiants.plan(session, cutoff)
            counts["artifacts_blocked"] = p.artifacts_blocked
            details = list(p.vehicle_details.items())
            for batch in _batches(details, batch_size):
                with session_scope() as session:
                    counts["vehicle_details"] += identifiants.empty_vehicle_details(session, dict(batch), operation_id)
                    session.commit()
            for batch in _batches(p.resolutions, batch_size):
                with session_scope() as session:
                    counts["resolutions"] += identifiants.empty_resolutions(session, batch, operation_id)
                    session.commit()
            with session_scope() as session:
                left = identifiants.remaining(session, cutoff)
            report.lines.append(Line(IDENTIFIERS.key, IDENTIFIERS.label, s.describe(),
                f"{counts['resolutions']} résolution(s) d'identité et {counts['vehicle_details']} fiche(s) véhicule "
                f"vidées ; vérification : {left['asset_identity_resolutions'] + left['vehicle_details']} copie(s) "
                f"échue(s) restante(s) hors artefacts ; {counts['artifacts_blocked']} artefact(s) vir_resolution "
                f"échu(s) gardent plaque et VIN (expurgation impossible sans évolution de CPL)"))
            counts["remaining"] = left["asset_identity_resolutions"] + left["vehicle_details"]
        else:
            report.lines.append(Line(IDENTIFIERS.key, IDENTIFIERS.label, s.describe(), "rien supprimé"))

        report.lines.append(Line(CASES.key, CASES.label, policy[CASES.key].describe(), "rien supprimé"))

        s = policy[MEDIA.key]
        if s.days is not None:
            media_dir = _media_dir(environ)
            if media_dir is None:
                raise PurgeRefused("PI05_MEDIA_STORAGE_DIR manquant : purge des médias impossible")
            with session_scope() as session:
                due = medias.due(session, _cutoff(s, now))
            for batch in _batches(due, batch_size):
                with session_scope() as session:
                    counts["media"] += medias.purge(session, media_dir, batch, operation_id)
                    session.commit()
            report.lines.append(Line(MEDIA.key, MEDIA.label, s.describe(), f"{counts['media']} média(s) supprimé(s)"))
        else:
            report.lines.append(Line(MEDIA.key, MEDIA.label, s.describe(), "rien supprimé"))

        s = policy[LOGS.key]
        montage_dir = _montage_dir(environ)
        if s.days is not None and montage_dir is not None:
            counts["logs"] = journaux.purge(journaux.due(montage_dir, _cutoff(s, now)))
            report.lines.append(Line(LOGS.key, LOGS.label, s.describe(), f"{counts['logs']} journal(aux) supprimé(s)"))
        else:
            report.lines.append(Line(LOGS.key, LOGS.label, s.describe(),
                                     "rien supprimé" + ("" if montage_dir else " (MONTAGE_DIR absent)")))
    except BaseException as exc:
        _finish_operation(operation_id, counts, "interrupted", type(exc).__name__)
        raise
    _finish_operation(operation_id, counts, "completed")
    return report
