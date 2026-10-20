"""Plate and VIN copies kept in CPL: what is due, and emptying it.

Where a plate or a VIN is kept in CPL (guide §9.1), and what is done here:

  cpl.asset_identity_resolutions.canonical_identity_payload.identifiers
      emptied: each identifier other than the registration country becomes
      null, and ``identifiers_not_kept`` lists which ones were removed (no
      replacement value). The record, its status, provenance, links and every
      other identity field stay.
  automotive.vehicle_details.vin_display / registration_display
      emptied (null) once no identification record still within its period
      holds the same value; make, model, country and links stay.
  cpl.runner_artifacts (vir_resolution) payload
      expurgated by CPL's governed operation (REQ-B6-091,
      app.cpl.runners.redaction.redact_artifact_identifiers), called here --
      never by SQL from PI. Since REQ-B6-091 a new artifact is registered
      without the plate and the VIN; an artifact registered before keeps them
      until its period is over. Same setting and same starting point
      (``enregistrement_cpl``): the creation of the identification record its
      execution wrote (the artifact's own registration when there is none,
      both being written in the same transaction). Every version linked by
      supersession is expurgated with it; an artifact whose content no longer
      matches its hash is refused by CPL, counted, never modified.

Each emptied record is written to pi_auth.identifier_expunctions with the
operation that emptied it: the fields' names, never their values.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.automotive.models.vehicle_detail import VehicleDetail
from app.cpl.models.asset_identity_resolution import AssetIdentityResolution
from app.cpl.identity.authority import AuthorityContext
from app.cpl.runners.authority import RunnerAuthority
from app.cpl.runners.outcomes import RunnerOutcome
from app.cpl.runners.redaction import plan_redaction, redact_artifact_identifiers

KEPT_IDENTIFIER_KEYS = ("registration_country",)    # not an identifier of the vehicle
NOT_KEPT_MARKER = "identifiers_not_kept"
_VEHICLE_DETAIL_FIELDS = {"vin": "vin_display", "registration_number": "registration_display"}


def scrub_identity(payload: dict) -> tuple[dict, list[str]]:
    """The identity without its identifiers (null), with the marker; and the
    names of the identifiers that held a value."""
    identifiers = dict((payload or {}).get("identifiers") or {})
    removed = sorted(k for k, v in identifiers.items() if k not in KEPT_IDENTIFIER_KEYS and v not in (None, ""))
    scrubbed = copy.deepcopy(payload or {})
    scrubbed["identifiers"] = {k: (v if k in KEPT_IDENTIFIER_KEYS else None) for k, v in identifiers.items()}
    scrubbed[NOT_KEPT_MARKER] = sorted(set(scrubbed.get(NOT_KEPT_MARKER) or []) | set(removed))
    return scrubbed, removed


def holds_identifier(payload: Optional[dict]) -> bool:
    identifiers = (payload or {}).get("identifiers") or {}
    return any(v not in (None, "") for k, v in identifiers.items() if k not in KEPT_IDENTIFIER_KEYS)


@dataclass
class IdentifierPlan:
    resolutions: list[UUID] = field(default_factory=list)
    vehicle_details: dict[UUID, list[str]] = field(default_factory=dict)   # asset_id -> columns to empty
    artifacts: list[UUID] = field(default_factory=list)          # vir_resolution artifacts to expurgate
    artifacts_refused: int = 0                                   # refused by CPL (content no longer matches its hash)


def _due_resolutions(session: Session, cutoff: datetime) -> Iterable[AssetIdentityResolution]:
    already = text("SELECT target_id FROM pi_auth.identifier_expunctions WHERE target_kind = 'asset_identity_resolution'")
    done = {row[0] for row in session.execute(already)}
    rows = (session.query(AssetIdentityResolution)
            .filter(AssetIdentityResolution.created_at < cutoff)
            .order_by(AssetIdentityResolution.created_at, AssetIdentityResolution.resolution_id))
    return (r for r in rows if r.resolution_id not in done and holds_identifier(r.canonical_identity_payload))


def _vehicle_detail_columns_due(session: Session, detail: VehicleDetail, cutoff: datetime) -> list[str]:
    """A copy on vehicle_details lives as long as an identification record of
    the same asset, still within its period, holds the same value. Without
    any such record: due once the asset has a record past its period, or,
    with no record at all, once the row itself was last written before the
    cutoff."""
    resolutions = session.query(AssetIdentityResolution).filter(AssetIdentityResolution.asset_id == detail.asset_id).all()
    current = [r for r in resolutions if r.created_at >= cutoff]
    any_due = any(r.created_at < cutoff for r in resolutions)
    due = []
    for key, column in _VEHICLE_DETAIL_FIELDS.items():
        value = getattr(detail, column)
        if value in (None, ""):
            continue
        held = any(((r.canonical_identity_payload or {}).get("identifiers") or {}).get(key) == value for r in current)
        if held:
            continue
        if any_due or (not resolutions and detail.updated_at < cutoff):
            due.append(column)
    return due


def _due_artifact_ids(session: Session, cutoff: datetime) -> list[UUID]:
    """vir_resolution artifacts whose identification record (or, without one,
    whose own registration) is past its period. Reads ids only."""
    return [row[0] for row in session.execute(text(
        "SELECT a.artifact_id FROM cpl.runner_artifacts a WHERE a.artifact_type = 'vir_resolution' "
        "AND a.schema_name = 'vir_resolution' AND coalesce((SELECT min(r.created_at) FROM "
        "cpl.asset_identity_resolutions r WHERE r.execution_id = a.execution_id), a.created_at) < :cutoff"),
        {"cutoff": cutoff})]


def _artifact_plan(session: Session, cutoff: datetime):
    ids = _due_artifact_ids(session, cutoff)
    return plan_redaction(session, artifact_ids=ids) if ids else None


def plan(session: Session, cutoff: datetime) -> IdentifierPlan:
    result = IdentifierPlan(resolutions=[r.resolution_id for r in _due_resolutions(session, cutoff)])
    for detail in session.query(VehicleDetail).filter(
            (VehicleDetail.vin_display.isnot(None)) | (VehicleDetail.registration_display.isnot(None))):
        columns = _vehicle_detail_columns_due(session, detail, cutoff)
        if columns:
            result.vehicle_details[detail.asset_id] = columns
    artifacts = _artifact_plan(session, cutoff)
    if artifacts is not None:
        result.artifacts = list(dict.fromkeys(artifacts.to_redact))
        result.artifacts_refused = len(artifacts.refused)
    return result


def expurgate_artifact(session: Session, artifact_id: UUID, operation_id: UUID) -> int:
    """CPL's governed expurgation of one artifact and its supersession chain,
    in the caller's transaction. Returns how many artifacts were expurgated
    (0: already done, or refused by CPL -- then nothing is written)."""
    authority = AuthorityContext(granted=frozenset({RunnerAuthority.REDACT_ARTIFACT}),
                                 actor_reference=f"pi-purge:{operation_id}")
    result = redact_artifact_identifiers(session, artifact_id=artifact_id, reason="RETENTION_POLICY",
                                         authority=authority, operation_id=operation_id)
    if result.outcome == RunnerOutcome.SUCCESS:
        return len(result.payload["redacted"])
    if result.outcome in (RunnerOutcome.NO_CHANGE, RunnerOutcome.CONFLICT, RunnerOutcome.NOT_FOUND):
        return 0
    raise RuntimeError(f"artifact expurgation refused: {result.outcome}")


def _record(session: Session, kind: str, target_id: UUID, fields: list[str], anchor_at, operation_id: UUID) -> None:
    session.execute(text(
        "INSERT INTO pi_auth.identifier_expunctions(target_kind, target_id, fields, anchor_at, operation_id) "
        "VALUES (:k, :t, :f, :a, :o) ON CONFLICT (target_kind, target_id) DO UPDATE SET "
        "fields = EXCLUDED.fields, anchor_at = EXCLUDED.anchor_at, operation_id = EXCLUDED.operation_id, "
        "expunged_at = now()"), {"k": kind, "t": target_id, "f": fields, "a": anchor_at, "o": operation_id})


def empty_vehicle_details(session: Session, columns_by_asset: dict[UUID, list[str]], operation_id: UUID) -> int:
    done = 0
    for asset_id, columns in columns_by_asset.items():
        detail = session.get(VehicleDetail, asset_id, with_for_update=True)
        if detail is None:
            continue
        emptied = [c for c in columns if getattr(detail, c) not in (None, "")]
        for column in emptied:
            setattr(detail, column, None)
        if emptied:
            _record(session, "vehicle_detail", asset_id, emptied, detail.updated_at, operation_id)
            done += 1
    session.flush()
    return done


def empty_resolutions(session: Session, resolution_ids: list[UUID], operation_id: UUID) -> int:
    done = 0
    for resolution_id in resolution_ids:
        resolution = session.get(AssetIdentityResolution, resolution_id, with_for_update=True)
        if resolution is None or not holds_identifier(resolution.canonical_identity_payload):
            continue
        scrubbed, removed = scrub_identity(resolution.canonical_identity_payload)
        resolution.canonical_identity_payload = scrubbed
        _record(session, "asset_identity_resolution", resolution_id, removed, resolution.created_at, operation_id)
        done += 1
    session.flush()
    return done


def remaining(session: Session, cutoff: datetime) -> dict[str, int]:
    """After an execution: copies past their period still holding a value
    (0 expected; artifacts refused by CPL for integrity counted apart)."""
    resolutions = sum(1 for r in session.query(AssetIdentityResolution).filter(AssetIdentityResolution.created_at < cutoff)
                      if holds_identifier(r.canonical_identity_payload))
    details = 0
    for detail in session.query(VehicleDetail).filter(
            (VehicleDetail.vin_display.isnot(None)) | (VehicleDetail.registration_display.isnot(None))):
        if _vehicle_detail_columns_due(session, detail, cutoff):
            details += 1
    artifacts = _artifact_plan(session, cutoff)
    return {"asset_identity_resolutions": resolutions, "vehicle_details": details,
            "vir_resolution_artifacts": len(artifacts.to_redact) if artifacts else 0}


def identification_not_kept(session: Session, execution_id: UUID) -> bool:
    """Whether the identification recorded by this VIR execution had its
    identifiers emptied by a purge."""
    return session.execute(text(
        "SELECT 1 FROM cpl.asset_identity_resolutions r JOIN pi_auth.identifier_expunctions e "
        "ON e.target_kind = 'asset_identity_resolution' AND e.target_id = r.resolution_id "
        "WHERE r.execution_id = :x LIMIT 1"), {"x": execution_id}).first() is not None
