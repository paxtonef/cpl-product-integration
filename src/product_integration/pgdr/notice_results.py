"""The confirmed result of the notice parcours, kept in CPL (bloc 3A, point 1).

Through CPL's existing structures only (no CPL schema change): one
RunnerExecution (runner type PGDR_V1_NOTICE, under the case, initiated by
its owner) and one artifact (schema pgdr_v1_premier_constat, registered
like vir_resolution), admitted, registered and reported COMPLETED in ONE
transaction. The idempotency key is derived from the record's content, so
the same result sent twice (double click, concurrent requests) is one
record.

What is kept: the case and its owner; the VIR resolution the parcours was
opened on (execution, artifact, VIR resolution id); the notice (document,
title, edition, language, content fingerprint); the entry_ids the DRIVER
selected -- a selection, never a recognition; the explicit confirmation and
its date; the Premier Constat and the exact sections PGDR produced for the
selected entries; provenance and limits. What is never kept: the photo, the
sorting answer or the proposed images, the catalogue, the parcours
identifier (image links are rewritten to the image digest).

A record is read back as it was confirmed: a later notice version never
replaces it, and reading needs neither PGDR nor any sorting.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.cpl.identity.authority import AuthorityContext
from app.cpl.models.case import Case
from app.cpl.models.runner_artifact import RunnerArtifact
from app.cpl.models.runner_artifact_schema_definition import RunnerArtifactSchemaDefinition
from app.cpl.models.runner_execution import RunnerExecution
from app.cpl.runners.artifacts import register_artifact
from app.cpl.runners.execution import admit_execution, persist_runner_report, transition_status
from app.cpl.runners.outcomes import RunnerOutcome
from app.db.engine import session_scope

from product_integration.api.deps import END_USER_GRANTS

RUNNER_TYPE = "PGDR_V1_NOTICE"
RUNNER_VERSION = "pgdr-v1"
PURPOSE = "notice_parcours_premier_constat"
SCHEMA_NAME = "pgdr_v1_premier_constat"
SCHEMA_VERSION = "1"
_REQUIRED = ["record_version", "case_id", "owner_contact_id", "vir", "notice", "selection", "confirmation",
             "premier_constat", "sections", "provenance", "limits"]
_NOTICE_FIELDS = ("document_id", "title", "edition", "language", "content_sha256")

LIMITS = (
    "Sélection faite par le conducteur dans les images de la notice : ce n'est pas une reconnaissance du voyant.",
    "La photo éventuelle n'est pas conservée ; des images proposées n'étaient qu'une aide à la sélection.",
    "Résultat figé à la date de confirmation, pour l'édition et l'empreinte de notice indiquées ; une notice "
    "ultérieure ne le modifie pas.",
)


class NotRecorded(Exception):
    """CPL refused the record; nothing was written."""


def _without_parcours_id(value, pid: str):
    """Image links name the parcours (/api/v1/parcours/<pid>/asset/<sha>); kept as the image digest only."""
    raw = json.dumps(value, ensure_ascii=False)
    return json.loads(raw.replace(f"/api/v1/parcours/{pid}/asset/", "notice-image:sha256:"))


def build_record(*, pid: str, case_id: UUID, owner_contact_id: UUID, vir: dict, state: dict,
                 confirmed_at: datetime) -> Optional[dict]:
    """The record of one restitution PGDR answered after an explicit confirmation, or None when `state` is not
    one (no restitution, no confirmation, no selection, no Premier Constat)."""
    document, constat, sections, selection = (state.get("document"), state.get("premier_constat"),
                                              state.get("sections"), state.get("selection"))
    if (state.get("phase") != "restitution" or state.get("confirmed") is not True or not isinstance(document, dict)
            or not isinstance(constat, dict) or not isinstance(sections, list) or not selection
            or not all(isinstance(x, str) for x in selection)):
        return None
    banners = [b for b in (state.get("dev_trial_banner"), state.get("tri_trial_banner")) if b]
    return {
        "record_version": 1,
        "case_id": str(case_id),
        "owner_contact_id": str(owner_contact_id),
        "vir": dict(vir),
        "notice": {k: document.get(k) for k in _NOTICE_FIELDS},
        "selection": {"entry_ids": list(selection), "by": "driver"},
        "confirmation": {"explicit": True, "confirmed_at": confirmed_at.isoformat()},
        "premier_constat": _without_parcours_id(constat, pid),
        "sections": _without_parcours_id(sections, pid),
        "provenance": {"service": "PGDR /v1 (parcours des voyants), relayé par PI", "selection_origin": "driver",
                       "trial_banners": banners},
        "limits": list(LIMITS) + banners,
    }


def _key(record: dict) -> str:
    content = {k: v for k, v in record.items() if k != "confirmation"}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"pgdr-v1-constat:{digest}"


def _ensure_schema() -> None:
    try:
        with session_scope() as session:
            if session.get(RunnerArtifactSchemaDefinition, (SCHEMA_NAME, SCHEMA_VERSION)) is None:
                session.add(RunnerArtifactSchemaDefinition(
                    schema_name=SCHEMA_NAME, schema_version=SCHEMA_VERSION, required_fields=_REQUIRED,
                    field_types={"record_version": "integer", "case_id": "string", "owner_contact_id": "string"},
                ))
                session.commit()
    except IntegrityError:
        pass  # registered by a concurrent writer


def _artifact_of(session, execution_id: UUID) -> Optional[UUID]:
    return session.query(RunnerArtifact.artifact_id).filter(
        RunnerArtifact.execution_id == execution_id, RunnerArtifact.schema_name == SCHEMA_NAME).scalar()


def persist(record: dict, *, case_id: UUID, contact_id: UUID, actor_reference: str) -> UUID:
    """Admission, artifact and COMPLETED report in one transaction; the same record again returns the artifact
    already kept. Raises NotRecorded (nothing written) when CPL refuses."""
    authority = AuthorityContext(granted=END_USER_GRANTS, actor_reference=actor_reference)
    _ensure_schema()
    key = _key(record)
    for _ in range(2):  # a concurrent writer of the same record: the second pass finds its row
        with session_scope() as session:
            case = session.get(Case, case_id)
            if case is None or case.primary_contact_id != contact_id:
                raise NotRecorded("case")
            admission = admit_execution(
                session, case_id=case_id, asset_id=case.asset_id, runner_type=RUNNER_TYPE,
                runner_version=RUNNER_VERSION, execution_purpose=PURPOSE, initiated_by_contact_id=contact_id,
                idempotency_key=key, authority=authority,
            )
            if admission.outcome != RunnerOutcome.SUCCESS:
                raise NotRecorded(admission.outcome)
            if admission.payload.get("replay"):
                existing = _artifact_of(session, admission.object_id)
                if existing is None:
                    continue
                return existing
            transition_status(session, execution_id=admission.object_id, new_status="RUNNING", authority=authority)
            artifact = register_artifact(
                session, execution_id=admission.object_id, artifact_type=SCHEMA_NAME, schema_name=SCHEMA_NAME,
                schema_version=SCHEMA_VERSION, payload=record, semantic_function="EXECUTION_OUTPUT_CARRIER",
                lifecycle_role="FINAL", presentation_role="PRODUCT_DISPLAYABLE", authority=authority,
            )
            report = persist_runner_report(session, execution_id=admission.object_id, new_status="COMPLETED",
                                           authority=authority)
            if artifact.outcome != RunnerOutcome.SUCCESS or report.outcome != RunnerOutcome.SUCCESS:
                session.rollback()
                raise NotRecorded("artifact")
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                continue
            return artifact.object_id
    raise NotRecorded("concurrent")


def results(session, case_id: UUID) -> list[dict]:
    """Every kept result of the case, oldest first, exactly as recorded (CPL only)."""
    found = (session.query(RunnerArtifact)
             .join(RunnerExecution, RunnerExecution.execution_id == RunnerArtifact.execution_id)
             .filter(RunnerExecution.case_id == case_id, RunnerExecution.runner_type == RUNNER_TYPE,
                     RunnerExecution.execution_status == "COMPLETED", RunnerArtifact.schema_name == SCHEMA_NAME)
             .order_by(RunnerArtifact.created_at).all())
    return [{"record_id": str(a.artifact_id), "recorded_at": a.created_at.isoformat(), **a.payload} for a in found]

