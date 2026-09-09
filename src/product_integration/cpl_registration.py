"""PI-01 orchestration: real VIR call -> governed CPL representation.

Transaction boundary (exact sequence required by the PI-01 instruction §17):

  TX1: admit_execution + transition to RUNNING (required pre-call state)  -> COMMIT
  -->  invoke VIR over HTTP (no open DB transaction during the network call)
  TX2 (on VIR success):  register_artifact + record_asset_identity_resolution +
                          write_vehicle_detail + persist_runner_report(COMPLETED) -> COMMIT
  TX_fail (on VIR technical failure, or TX2 failure): persist_runner_report(FAILED)
                          in its own short transaction -> COMMIT

CPL distinctions preserved throughout (B6, unchanged, not reopened):
  REQUEST != AUTHORIZATION != EXECUTION != EXECUTION_STATUS != DOMAIN_RESULT
A successful HTTP 200 from VIR is not a successful vehicle-identity
resolution (resolution_status may be ambiguous/contradictory/etc. even on
HTTP 200) — execution_status only ever reflects whether VIR responded, not
what it concluded. Conversely, a VIR technical failure (transport/timeout/
invalid-response/VIRBaseError) is execution_status=FAILED, never encoded as
a resolution_status value, because no resolution was reached at all.

RunnerArtifact remains representation-only throughout — nothing here
computes or asserts vehicle-identity truth; VIR's own conclusion is stored
opaquely (REQ-B6-016/069, unchanged since B6).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from app.cpl.identity.authority import AuthorityContext
from app.cpl.assets.resolution import record_asset_identity_resolution
from app.cpl.models.asset_identity_resolution import AssetIdentityResolution
from app.cpl.models.runner_artifact import RunnerArtifact
from app.cpl.runners.execution import admit_execution, transition_status, persist_runner_report
from app.cpl.runners.artifacts import register_artifact
from app.cpl.runners.outcomes import RunnerOutcome
from app.cpl.models.runner_artifact_schema_definition import RunnerArtifactSchemaDefinition
from app.db.engine import session_scope

from product_integration.vir.client import VIRClient
from product_integration.vir.errors import VIRClientError
from product_integration.vir.schemas import VehicleIdentityRequest, VehicleIdentityResolution
from product_integration.vir.status_mapping import map_vir_status_to_cpl
from product_integration.vehicle_detail_writer import write_vehicle_detail

VIR_RESOLUTION_SCHEMA_NAME = "vir_resolution"
VIR_RESOLUTION_SCHEMA_VERSION = "1"


class VIRRegistrationOutcome:
    SUCCESS = "SUCCESS"
    AUTHORITY_REJECTION = "AUTHORITY_REJECTION"
    CONFLICT = "CONFLICT"
    VIR_TECHNICAL_FAILURE = "VIR_TECHNICAL_FAILURE"
    CPL_PERSISTENCE_FAILURE = "CPL_PERSISTENCE_FAILURE"


@dataclass
class VIRRegistrationResult:
    outcome: str
    execution_id: Optional[UUID] = None
    artifact_id: Optional[UUID] = None
    resolution_id: Optional[UUID] = None  # CPL AssetIdentityResolution.resolution_id
    vir_resolution_id: Optional[str] = None  # VIR's own resolution_id (string)
    cpl_resolution_status: Optional[str] = None
    detail: Optional[str] = None


def ensure_vir_resolution_schema_registered(session) -> None:
    """Idempotent: registers the minimal structural contract for
    'vir_resolution' artifacts (REQ-B6-089's existing mechanism — no new
    registry is built here). Required fields kept minimal and non-
    speculative per §15: enough for reproducibility and later PI units,
    nothing predicting PGDR's implementation beyond the Reality Check."""
    existing = session.get(
        RunnerArtifactSchemaDefinition, (VIR_RESOLUTION_SCHEMA_NAME, VIR_RESOLUTION_SCHEMA_VERSION)
    )
    if existing is not None:
        return
    session.add(RunnerArtifactSchemaDefinition(
        schema_name=VIR_RESOLUTION_SCHEMA_NAME,
        schema_version=VIR_RESOLUTION_SCHEMA_VERSION,
        required_fields=["resolution_id", "resolution_status"],
        field_types={"resolution_id": "string", "resolution_status": "string"},
    ))


async def register_vir_execution(
    *,
    vir_client: VIRClient,
    case_id: UUID,
    asset_id: UUID,
    vir_request: VehicleIdentityRequest,
    authority: AuthorityContext,
    resolver_version: str = "unknown",
) -> VIRRegistrationResult:
    """The PI-01 entry point: performs one real VIR resolve() call and
    represents it as governed CPL state, per the exact transaction
    boundary this module's docstring describes."""

    # -- TX1: admit + pre-call state -----------------------------------
    with session_scope() as session:
        admission = admit_execution(
            session, case_id=case_id, asset_id=asset_id, runner_type="VIR",
            runner_version=resolver_version, execution_purpose="vehicle_identity_resolution",
            idempotency_key=vir_request.request_id, authority=authority,
        )
        if admission.outcome != RunnerOutcome.SUCCESS:
            session.commit()
            # Distinguish CONFLICT (idempotency_key reused with materially
            # different intent, REQ-B6-037) from a genuine authority
            # rejection — collapsing these into one label would itself be
            # exactly the "convert all failures into one generic state"
            # anti-pattern §18 prohibits.
            mapped_outcome = (
                VIRRegistrationOutcome.CONFLICT if admission.outcome == RunnerOutcome.CONFLICT
                else VIRRegistrationOutcome.AUTHORITY_REJECTION
            )
            return VIRRegistrationResult(
                outcome=mapped_outcome,
                detail=f"admission outcome was {admission.outcome!r}: {admission.detail}",
            )
        execution_id = admission.object_id
        was_replay = bool(admission.payload.get("replay"))
        if was_replay:
            # REQ-B6-036: same idempotency_key + same governed operation ->
            # admit_execution already retrieved the existing, already-
            # processed RunnerExecution. Re-running the VIR call and TX2
            # here would register a second artifact for the same execution
            # — a genuine bug if not guarded against. Return the existing
            # linked state instead of re-registering anything.
            session.commit()
            return _existing_registration_result(execution_id)
        # REQ-B6-009's transition table requires CREATED -> RUNNING before
        # RUNNING -> COMPLETED (COMPLETED is not directly reachable from
        # CREATED) — this is "required pre-call state" per §17.
        transition_status(session, execution_id=execution_id, new_status="RUNNING", authority=authority)
        session.commit()

    # -- HTTP call to VIR, no open DB transaction ----------------------
    try:
        vir_resolution: VehicleIdentityResolution = await vir_client.resolve(vir_request)
    except VIRClientError as exc:
        return _mark_failed(execution_id, detail=f"VIR technical failure: {exc}", authority=authority)

    # -- TX2: persist the successful (possibly inconclusive) result ----
    try:
        with session_scope() as session:
            ensure_vir_resolution_schema_registered(session)

            artifact_result = register_artifact(
                session, execution_id=execution_id, artifact_type="vir_resolution",
                schema_name=VIR_RESOLUTION_SCHEMA_NAME, schema_version=VIR_RESOLUTION_SCHEMA_VERSION,
                payload=vir_resolution.model_dump(mode="json"),
                semantic_function="DOMAIN_DETERMINATION_CARRIER", lifecycle_role="FINAL",
                presentation_role="INTERNAL", authority=authority,
            )
            if artifact_result.outcome != RunnerOutcome.SUCCESS:
                session.rollback()
                return _mark_failed(
                    execution_id, detail=f"artifact registration outcome {artifact_result.outcome!r}",
                    authority=authority,
                )

            cpl_status = map_vir_status_to_cpl(vir_resolution.resolution_status)

            canonical_identity = (
                vir_resolution.vehicle_identity.model_dump(mode="json")
                if vir_resolution.vehicle_identity is not None else {}
            )
            resolution_result = record_asset_identity_resolution(
                session, asset_id=asset_id, resolver_type="VIR", resolver_version=resolver_version,
                resolution_status=cpl_status, canonical_identity_payload=canonical_identity,
                confidence=vir_resolution.confidence.score if vir_resolution.confidence else None,
                execution_id=execution_id, provenance_payload={"vir_resolution_id": vir_resolution.resolution_id},
                authority=authority,
            )
            if resolution_result.outcome != RunnerOutcome.SUCCESS:
                session.rollback()
                return _mark_failed(
                    execution_id, detail=f"resolution recording outcome {resolution_result.outcome!r}",
                    authority=authority,
                )

            # §24-E: ambiguous/unresolved outcomes do not become accepted
            # identity by convenience — VehicleDetail (a display/summary
            # projection treated as accepted identity data) is written
            # only when CPL's own resolution_status indicates a usable
            # identity was actually produced.
            if cpl_status in ("RESOLVED", "PARTIALLY_RESOLVED") and vir_resolution.vehicle_identity is not None:
                write_vehicle_detail(
                    session, asset_id=asset_id, source_resolution_id=resolution_result.object_id,
                    canonical_identity=canonical_identity,
                )

            report_result = persist_runner_report(
                session, execution_id=execution_id, new_status="COMPLETED", authority=authority,
            )
            if report_result.outcome != RunnerOutcome.SUCCESS:
                session.rollback()
                return _mark_failed(
                    execution_id, detail=f"final report outcome {report_result.outcome!r}", authority=authority,
                )

            session.commit()
            return VIRRegistrationResult(
                outcome=VIRRegistrationOutcome.SUCCESS,
                execution_id=execution_id, artifact_id=artifact_result.object_id,
                resolution_id=resolution_result.object_id, vir_resolution_id=vir_resolution.resolution_id,
                cpl_resolution_status=cpl_status,
            )
    except Exception as exc:  # noqa: BLE001 — genuine CPL persistence failure, §24-H
        return _mark_failed(execution_id, detail=f"CPL persistence failure: {exc}", authority=authority,
                             outcome=VIRRegistrationOutcome.CPL_PERSISTENCE_FAILURE)


def _existing_registration_result(execution_id: UUID) -> VIRRegistrationResult:
    """REQ-B6-036 replay: reconstructs the result from the already-
    persisted state of a prior, already-completed registration for this
    exact execution_id, rather than re-deriving anything."""
    with session_scope() as session:
        artifact = (
            session.query(RunnerArtifact)
            .filter(RunnerArtifact.execution_id == execution_id, RunnerArtifact.artifact_type == "vir_resolution")
            .order_by(RunnerArtifact.created_at.desc())
            .first()
        )
        resolution = None
        vir_resolution_id = None
        if artifact is not None:
            vir_resolution_id = artifact.payload.get("resolution_id")
            resolution = (
                session.query(AssetIdentityResolution)
                .filter(AssetIdentityResolution.execution_id == execution_id)
                .order_by(AssetIdentityResolution.created_at.desc())
                .first()
            )
        return VIRRegistrationResult(
            outcome=VIRRegistrationOutcome.SUCCESS,
            execution_id=execution_id,
            artifact_id=artifact.artifact_id if artifact is not None else None,
            resolution_id=resolution.resolution_id if resolution is not None else None,
            vir_resolution_id=vir_resolution_id,
            cpl_resolution_status=resolution.resolution_status if resolution is not None else None,
            detail="replay: returned existing linked state, no new registration performed",
        )


def _mark_failed(
    execution_id: UUID, *, detail: str, authority: AuthorityContext,
    outcome: str = VIRRegistrationOutcome.VIR_TECHNICAL_FAILURE,
) -> VIRRegistrationResult:
    """Best-effort: mark the already-admitted execution FAILED in its own
    short transaction. If this itself fails (e.g. the DB is genuinely
    down), the original failure is still reported — this function never
    swallows the caller's failure to report its own."""
    try:
        with session_scope() as session:
            persist_runner_report(session, execution_id=execution_id, new_status="FAILED", authority=authority)
            session.commit()
    except Exception:  # noqa: BLE001 — best-effort only, never masks the original failure
        pass
    return VIRRegistrationResult(outcome=outcome, execution_id=execution_id, detail=detail)
