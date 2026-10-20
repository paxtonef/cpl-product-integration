"""The purge: simulation (default) and execution, category by category.

Simulation reads only and works without any policy ("aucune politique, rien
ne serait supprimé"); one simulation shows every category. Execution refuses
before any write unless every category it covers has an explicit policy
(policy.py). Order of the execution (each step through CPL's governed
operations, never SQL into CPL rows from PI):

  1. vir_resolution artifacts past their period: plate and VIN expurgated
     (REQ-B6-091; setting and starting point of the identifiers);
  2. cases past their period: deleted with their own data (REQ-B5-116,
     dossiers.py), irreversibly;
  3. identifier copies past their period in what remains (identifiants.py);
  4. media past their period; 5. rotated logs.

Expurgating first means no case kept past step 2 still exposes an expired
identifier in an artifact; deleting cases before step 3 avoids emptying rows
about to be deleted. Web sessions and VIR's store are purged after this, by
deploy/purger.sh; backups and copies set aside by a restoration by
deploy/nettoyer_sauvegardes.sh.

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

from product_integration.conservation import dossiers, identifiants, journaux, medias, sauvegardes
from product_integration.conservation.policy import (
    BACKUPS, CASES, IDENTIFIERS, LOGS, MEDIA, PURGE_CATEGORIES, Setting, read_policy,
)

DEFAULT_BATCH = 200
NO_POLICY = "aucune politique, rien ne serait supprimé"
ARTIFACTS_KEY = "artefacts"
ARTIFACTS_LABEL = "plaque et VIN des artefacts vir_resolution (réglage des identifiants)"
MEDIA_NOT_CASES = (" ; conservation propre aux médias : aucun média n'est rattaché à un dossier dans le modèle "
                   "actuel, la suppression d'un dossier n'en supprime aucun")


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
    return reasons


def _artifacts_detail(n: int, refused: int, conditional: bool) -> str:
    verb = "seraient expurgés" if conditional else "expurgé(s)"
    return (f"{n} artefact(s) vir_resolution échu(s) {verb} de plaque et VIN par l'opération CPL REQ-B6-091 "
            f"(toutes versions liées) ; {refused} refusé(s) par CPL (contenu différent de son empreinte, non modifié)")


def _identifiers_detail(resolutions: int, details: int, conditional: bool) -> str:
    verb = "seraient vidées" if conditional else "vidées"
    return f"{resolutions} résolution(s) d'identité et {details} fiche(s) véhicule {verb} de plaque et VIN"


def _undefined_or_unlimited(s: Setting, executed: bool) -> str:
    if not s.defined:
        return NO_POLICY
    return "rien supprimé" if executed else "rien ne serait supprimé"


def simulate(environ=None, now: Optional[datetime] = None) -> Report:
    """Every category, in the order of the execution: vir_resolution artifacts,
    cases, identifier copies, media, logs; then what this command does not
    execute itself (web sessions, backups and copies set aside by a
    restoration), shown so that one simulation covers everything."""
    environ = os.environ if environ is None else environ
    now = now or datetime.now(timezone.utc)
    policy = read_policy(environ)
    report = Report(executed=False)
    with session_scope() as session:
        s = policy[IDENTIFIERS.key]
        if s.days is None:
            report.lines.append(Line(ARTIFACTS_KEY, ARTIFACTS_LABEL, s.describe(), _undefined_or_unlimited(s, False)))
            ident_plan = None
        else:
            ident_plan = identifiants.plan(session, _cutoff(s, now))
            report.counts.update(artifacts=len(ident_plan.artifacts), artifacts_refused=ident_plan.artifacts_refused)
            report.lines.append(Line(ARTIFACTS_KEY, ARTIFACTS_LABEL, s.describe(), _artifacts_detail(
                len(ident_plan.artifacts), ident_plan.artifacts_refused, conditional=True)))

        s = policy[CASES.key]
        if s.days is None:
            total = session.execute(text("SELECT count(*) FROM cpl.cases")).scalar()
            report.counts["cases_total"] = total
            report.lines.append(Line(CASES.key, CASES.label, s.describe(),
                                     _undefined_or_unlimited(s, False) + f" ({total} dossier(s) en base)"))
        else:
            p = dossiers.plan(session, _cutoff(s, now))
            report.counts.update(cases=len(p.due), cases_blocked=len(p.blocked))
            report.lines.append(Line(CASES.key, CASES.label, s.describe(), _cases_detail(
                len(p.due), p.counts, len(p.blocked), conditional=True)))

        s = policy[IDENTIFIERS.key]
        if ident_plan is None:
            report.lines.append(Line(IDENTIFIERS.key, IDENTIFIERS.label, s.describe(),
                                     _undefined_or_unlimited(s, False)))
        else:
            report.counts.update(resolutions=len(ident_plan.resolutions), vehicle_details=len(ident_plan.vehicle_details))
            report.lines.append(Line(IDENTIFIERS.key, IDENTIFIERS.label, s.describe(), _identifiers_detail(
                len(ident_plan.resolutions), len(ident_plan.vehicle_details), conditional=True)))

        s = policy[MEDIA.key]
        media_dir = _media_dir(environ)
        if s.days is None:
            report.lines.append(Line(MEDIA.key, MEDIA.label, s.describe(),
                                     _undefined_or_unlimited(s, False) + MEDIA_NOT_CASES))
        else:
            due = medias.due(session, _cutoff(s, now))
            orphans = medias.orphan_files(session, media_dir) if media_dir else 0
            report.counts.update(media=len(due), media_orphans=orphans)
            report.lines.append(Line(MEDIA.key, MEDIA.label, s.describe(),
                f"{len(due)} média(s) seraient supprimés ; {orphans} fichier(s) sans propriétaire, non traités"
                + MEDIA_NOT_CASES))
        expired_sessions = session.execute(text(
            "SELECT count(*) FROM pi_auth.web_sessions WHERE expires_at <= now()")).scalar()

    s = policy[LOGS.key]
    montage_dir = _montage_dir(environ)
    if s.days is None:
        report.lines.append(Line(LOGS.key, LOGS.label, s.describe(), _undefined_or_unlimited(s, False)))
    else:
        due_logs = journaux.due(montage_dir, _cutoff(s, now)) if montage_dir else []
        report.counts["logs"] = len(due_logs)
        report.lines.append(Line(LOGS.key, LOGS.label, s.describe(),
            f"{len(due_logs)} journal(aux) tourné(s) seraient supprimés" if montage_dir
            else "MONTAGE_DIR absent : aucun journal examiné"))

    report.counts["sessions_expired"] = expired_sessions
    report.lines.append(Line("sessions", "sessions web expirées", "durée de session PI_SESSION_*",
                             f"{expired_sessions} session(s) expirée(s) seraient supprimées (purge-sessions, "
                             f"exécutée par deploy/purger.sh --executer)"))
    report.lines.extend(_backup_lines(environ, policy[BACKUPS.key], now, report.counts))
    return report


def _backup_lines(environ, setting: Setting, now: datetime, counts: dict) -> list[Line]:
    """Backups and copies set aside by a restoration: counts only; deleted
    by deploy/nettoyer_sauvegardes.sh, never by this purge."""
    root = Path(environ["SAUVEGARDES_DIR"]) if environ.get("SAUVEGARDES_DIR") else None
    vir_db = Path(environ["VIR_DATABASE_PATH"]) if environ.get("VIR_DATABASE_PATH") else None
    found = sauvegardes.inventory(root, _media_dir(environ), vir_db)
    lines = []
    for kind, label in sauvegardes.KINDS.items():
        items = [f for f in found if f.kind == kind]
        recognised = [f for f in items if f.recognised]
        if setting.days is None:
            due_text = _undefined_or_unlimited(setting, False)
        else:
            due_n = len(sauvegardes.due(recognised, now - timedelta(days=setting.days)))
            due_text = f"{due_n} échue(s) seraient supprimées par deploy/nettoyer_sauvegardes.sh --executer"
        counts[f"{kind}_reconnues"] = len(recognised)
        counts[f"{kind}_non_reconnues"] = len(items) - len(recognised)
        lines.append(Line(BACKUPS.key, label, setting.describe(),
                          f"{len(recognised)} reconnue(s), {len(items) - len(recognised)} non reconnue(s) (jamais "
                          f"supprimées, à traiter par l'opérateur) ; {due_text}"))
    lines.append(Line(BACKUPS.key, "base PostgreSQL avant restauration", setting.describe(),
                      "aucune copie mise de côté : deploy/restaurer.sh remplace la base en place ; l'état antérieur "
                      "n'existe que dans une sauvegarde prise avant"))
    return lines


def _cases_detail(n: int, counts: dict, blocked: int, conditional: bool) -> str:
    verb = "seraient supprimés" if conditional else "supprimé(s)"
    return (f"{n} dossier(s) échu(s) {verb} avec leurs données propres "
            f"({counts.get('runner_executions', 0)} exécution(s), {counts.get('runner_artifacts', 0)} artefact(s) "
            f"dont résultats confirmés, {counts.get('asset_identity_resolutions', 0)} résolution(s) d'identité) ; "
            f"comptes, véhicules, autres dossiers et connaissances conservés ; {blocked} dossier(s) échu(s) "
            f"reporté(s) (une donnée hors du dossier en dépend)")


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
    counts = {"artifacts": 0, "artifacts_refused": 0, "cases": 0, "cases_blocked": 0, "resolutions": 0,
              "vehicle_details": 0, "media": 0, "logs": 0}
    report = Report(executed=True, operation_id=operation_id, counts=counts)
    try:
        # 1. vir_resolution artifacts past their period: CPL's governed expurgation, one artifact (and its
        #    supersession chain) per transaction.
        s = policy[IDENTIFIERS.key]
        if s.days is not None:
            cutoff = _cutoff(s, now)
            with session_scope() as session:
                p = identifiants.plan(session, cutoff)
            for artifact_id in p.artifacts:
                with session_scope() as session:
                    counts["artifacts"] += identifiants.expurgate_artifact(session, artifact_id, operation_id)
                    session.commit()
            counts["artifacts_refused"] = p.artifacts_refused
            report.lines.append(Line(ARTIFACTS_KEY, ARTIFACTS_LABEL, s.describe(),
                                     _artifacts_detail(counts["artifacts"], p.artifacts_refused, False)))
        else:
            report.lines.append(Line(ARTIFACTS_KEY, ARTIFACTS_LABEL, s.describe(), "rien supprimé"))

        # 2. cases past their period: CPL's governed deletion, one case per transaction.
        s = policy[CASES.key]
        if s.days is not None:
            cutoff = _cutoff(s, now)
            with session_scope() as session:
                due = list(dossiers.plan(session, cutoff).due)
            deleted_rows: dict[str, int] = {}
            for case_id in due:
                with session_scope() as session:
                    outcome = dossiers.delete_one(session, case_id, cutoff, s.days, operation_id)
                    session.commit()
                counts["cases"] += int(outcome.deleted)
                for kind, n in outcome.counts.items():
                    deleted_rows[kind] = deleted_rows.get(kind, 0) + n
            with session_scope() as session:
                counts["cases_blocked"] = len(dossiers.plan(session, cutoff).blocked)
            report.lines.append(Line(CASES.key, CASES.label, s.describe(),
                                     _cases_detail(counts["cases"], deleted_rows, counts["cases_blocked"], False)))
        else:
            report.lines.append(Line(CASES.key, CASES.label, s.describe(), "rien supprimé"))

        # 3. identifier copies (identity resolutions, vehicle details) of what remains, in batches.
        s = policy[IDENTIFIERS.key]
        if s.days is not None:
            cutoff = _cutoff(s, now)
            with session_scope() as session:
                p = identifiants.plan(session, cutoff)
            for batch in _batches(list(p.vehicle_details.items()), batch_size):
                with session_scope() as session:
                    counts["vehicle_details"] += identifiants.empty_vehicle_details(session, dict(batch), operation_id)
                    session.commit()
            for batch in _batches(p.resolutions, batch_size):
                with session_scope() as session:
                    counts["resolutions"] += identifiants.empty_resolutions(session, batch, operation_id)
                    session.commit()
            with session_scope() as session:
                left = identifiants.remaining(session, cutoff)
            counts["remaining"] = sum(left.values())
            report.lines.append(Line(IDENTIFIERS.key, IDENTIFIERS.label, s.describe(),
                _identifiers_detail(counts["resolutions"], counts["vehicle_details"], False)
                + f" ; vérification : {counts['remaining']} copie(s) échue(s) restante(s), artefacts compris "
                  f"(hors {counts['artifacts_refused']} artefact(s) refusé(s) par CPL)"))
        else:
            report.lines.append(Line(IDENTIFIERS.key, IDENTIFIERS.label, s.describe(), "rien supprimé"))

        # 4. media, 5. rotated logs.
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
            report.lines.append(Line(MEDIA.key, MEDIA.label, s.describe(),
                                     f"{counts['media']} média(s) supprimé(s)" + MEDIA_NOT_CASES))
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
