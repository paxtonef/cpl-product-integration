"""PI-01 orchestration: real VIR results -> governed CPL representation.

Repair of PI-01-VF-01 (independent verification, docs/build/
PI_01_INDEPENDENT_VERIFICATION_v0.md @ dc3ac32): VIR INVOCATION is now
separated from CPL REGISTRATION OF A VIR RESULT. There are two public entry
points, both converging on the same internal persistence path
(`_persist_vir_resolution`):

  register_vir_execution(...)          Path A — ordinary resolution. Calls
                                        VIR's resolve() itself, then persists
                                        whatever it gets back.

  register_vir_resolution_result(...)  Path B — an already-obtained VIR
                                        result (e.g. the output of
                                        VIRClient.submit_clarification(),
                                        called by the caller BEFORE this
                                        function, not by this function).
                                        Never calls resolve(). Persists the
                                        exact resolution object it is given,
                                        using its own resolution_id — never
                                        substituted, never discarded.

Transaction boundary (unchanged from the original candidate, §17):

  TX1: admit_execution + transition to RUNNING (required pre-call state)  -> COMMIT
  -->  [Path A only] invoke VIR over HTTP, no open DB transaction during the call
  TX2 (shared): register_artifact + record_asset_identity_resolution +
                write_vehicle_detail + persist_runner_report(COMPLETED) -> COMMIT
  TX_fail: persist_runner_report(FAILED) in its own short transaction -> COMMIT

Execution identity (§7 of the repair instruction): a clarified VIR
resolution carries VIR's own, genuinely distinct resolution_id (confirmed
directly against VIR's real behavior during independent verification — a
new resolution_id, not an update to the original). Per CPL's own,
unmodified B6 discipline ("NEW EXECUTION ATTEMPT -> NEW RUNNEREXECUTION",
REQ-B6-004, and "CORRECTION OF EXECUTION REPRESENTATION != REWRITING
HISTORICAL EXECUTION OCCURRENCE", REQ-B6-062), each distinct VIR
resolution_id is registered as its own RunnerExecution — the clarified
result is never retrofitted onto the original (now-historical) execution's
already-final artifact/resolution. This is not a guess: it follows directly
from applying B6's existing, unchanged rules to VIR's own observed
resolution_id behavior, rather than inventing new CPL execution semantics.
The relationship between the two executions (if the caller knows it) is
recorded as plain data in AssetIdentityResolution.provenance_payload — an
existing, already-used JSONB field — never via parent_execution_id (still
never assigned canonical meaning, REQ-B6-006/043, unchanged) and never via
any new CPL schema.

CPL distinctions preserved throughout (B6, unchanged, not reopened):
  REQUEST != AUTHORIZATION != EXECUTION != EXECUTION_STATUS != DOMAIN_RESULT
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
    speculative per the Reality Check's §15: enough for reproducibility and
    later PI units, nothing predicting PGDR's implementation. Unchanged by
    this repair — both Path A and Path B produce a payload with these same
    two fields present, since both persist a real VehicleIdentityResolution."""
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


def _admit_and_prepare(
    *, case_id: UUID, asset_id: UUID, idempotency_key: str, execution_purpose: str,
    resolver_version: str, authority: AuthorityContext,
) -> tuple[UUID, bool]:
    """Shared TX1: admit_execution + (if genuinely new) transition to
    RUNNING, both in one committed transaction — the exact "required
    pre-call state" §17 always required, unchanged by this repair. Returns
    (execution_id, was_replay). Used by both Path A (before an HTTP call)
    and Path B (before persisting an already-obtained result — there is no
    HTTP call on Path B, but the same "required state before the governed
    effect" discipline still applies)."""
    with session_scope() as session:
        admission = admit_execution(
            session, case_id=case_id, asset_id=asset_id, runner_type="VIR",
            runner_version=resolver_version, execution_purpose=execution_purpose,
            idempotency_key=idempotency_key, authority=authority,
        )
        if admission.outcome != RunnerOutcome.SUCCESS:
            session.commit()
            raise _AdmissionRejected(admission.outcome, admission.detail)
        execution_id = admission.object_id
        was_replay = bool(admission.payload.get("replay"))
        if not was_replay:
            # REQ-B6-009's transition table requires CREATED -> RUNNING
            # before RUNNING -> COMPLETED (COMPLETED is not directly
            # reachable from CREATED) — unchanged by this repair.
            transition_status(session, execution_id=execution_id, new_status="RUNNING", authority=authority)
        session.commit()
        return execution_id, was_replay


class _AdmissionRejected(Exception):
    def __init__(self, outcome: str, detail: Optional[str]):
        super().__init__(detail)
        self.outcome = outcome
        self.detail = detail


def _persist_vir_resolution(
    *, execution_id: UUID, asset_id: UUID, vir_resolution: VehicleIdentityResolution,
    resolver_version: str, authority: AuthorityContext, extra_provenance: Optional[dict] = None,
) -> VIRRegistrationResult:
    """The single canonical TX2 persistence path (§5 of the repair
    instruction): register_artifact + record_asset_identity_resolution +
    conditional write_vehicle_detail + persist_runner_report(COMPLETED),
    all in one committed transaction. Both Path A and Path B call this
    exact function — there is no duplicate persistence logic anywhere in
    this module. Behavior is byte-for-byte the same as the original
    candidate's TX2 block; only its location changed (extracted, not
    rewritten)."""
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
            provenance_payload = {"vir_resolution_id": vir_resolution.resolution_id}
            if extra_provenance:
                provenance_payload.update(extra_provenance)

            resolution_result = record_asset_identity_resolution(
                session, asset_id=asset_id, resolver_type="VIR", resolver_version=resolver_version,
                resolution_status=cpl_status, canonical_identity_payload=canonical_identity,
                confidence=vir_resolution.confidence.score if vir_resolution.confidence else None,
                execution_id=execution_id, provenance_payload=provenance_payload,
                authority=authority,
            )
            if resolution_result.outcome != RunnerOutcome.SUCCESS:
                session.rollback()
                return _mark_failed(
                    execution_id, detail=f"resolution recording outcome {resolution_result.outcome!r}",
                    authority=authority,
                )

            # Ambiguous/unresolved outcomes do not become accepted identity
            # by convenience — VehicleDetail is written only when CPL's own
            # resolution_status indicates a usable identity was actually
            # produced. Unchanged by this repair; applies identically
            # whether the resolution came from Path A or Path B.
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
    except Exception as exc:  # noqa: BLE001 — genuine CPL persistence failure
        return _mark_failed(execution_id, detail=f"CPL persistence failure: {exc}", authority=authority,
                             outcome=VIRRegistrationOutcome.CPL_PERSISTENCE_FAILURE)


async def register_vir_execution(
    *,
    vir_client: VIRClient,
    case_id: UUID,
    asset_id: UUID,
    vir_request: VehicleIdentityRequest,
    authority: AuthorityContext,
    resolver_version: str = "unknown",
) -> VIRRegistrationResult:
    """Path A — ordinary resolution: performs one real VIR resolve() call
    and represents it as governed CPL state. Unchanged in outward behavior
    from the original candidate; internally now a thin wrapper around the
    shared TX1 (`_admit_and_prepare`) and TX2 (`_persist_vir_resolution`)
    functions rather than inlining both."""
    try:
        execution_id, was_replay = _admit_and_prepare(
            case_id=case_id, asset_id=asset_id, idempotency_key=vir_request.request_id,
            execution_purpose="vehicle_identity_resolution", resolver_version=resolver_version,
            authority=authority,
        )
    except _AdmissionRejected as rejected:
        mapped_outcome = (
            VIRRegistrationOutcome.CONFLICT if rejected.outcome == RunnerOutcome.CONFLICT
            else VIRRegistrationOutcome.AUTHORITY_REJECTION
        )
        return VIRRegistrationResult(outcome=mapped_outcome, detail=f"admission outcome was {rejected.outcome!r}: {rejected.detail}")

    if was_replay:
        # REQ-B6-036: same idempotency_key + same governed operation ->
        # admit_execution already retrieved the existing, already-processed
        # RunnerExecution. Re-running the VIR call and TX2 here would
        # register a second artifact for the same execution.
        return _existing_registration_result(execution_id)

    # -- HTTP call to VIR, no open DB transaction ----------------------
    try:
        vir_resolution: VehicleIdentityResolution = await vir_client.resolve(vir_request)
    except VIRClientError as exc:
        return _mark_failed(execution_id, detail=f"VIR technical failure: {exc}", authority=authority)

    return _persist_vir_resolution(
        execution_id=execution_id, asset_id=asset_id, vir_resolution=vir_resolution,
        resolver_version=resolver_version, authority=authority,
    )


def register_vir_resolution_result(
    *,
    vir_resolution: VehicleIdentityResolution,
    case_id: UUID,
    asset_id: UUID,
    authority: AuthorityContext,
    resolver_version: str = "unknown",
    clarifies_execution_id: Optional[UUID] = None,
    clarifies_resolution_id: Optional[str] = None,
) -> VIRRegistrationResult:
    """Path B — register an ALREADY-OBTAINED VIR result (this is the
    PI-01-VF-01 repair). The caller obtains `vir_resolution` however it
    needs to — typically via `VIRClient.submit_clarification()`, called
    BEFORE this function, never inside it. This function never calls
    `vir_client.resolve()`; it persists exactly the resolution object it is
    given, using that resolution's own `resolution_id` (never substituted,
    never discarded, never regenerated).

    `clarifies_execution_id`/`clarifies_resolution_id` are optional: if the
    caller knows this result clarifies a specific earlier execution/
    resolution, that relationship is recorded as plain provenance data
    (AssetIdentityResolution.provenance_payload — an existing JSONB field
    already used for VIR resolution_id tracking, not a new CPL schema
    element) rather than left silently untracked. Per REQ-B6-006/043
    (unchanged), this is never recorded via parent_execution_id."""
    idempotency_key = vir_resolution.resolution_id  # the clarified result's own VIR resolution_id
    execution_purpose = "vehicle_identity_resolution_clarification"

    try:
        execution_id, was_replay = _admit_and_prepare(
            case_id=case_id, asset_id=asset_id, idempotency_key=idempotency_key,
            execution_purpose=execution_purpose, resolver_version=resolver_version, authority=authority,
        )
    except _AdmissionRejected as rejected:
        mapped_outcome = (
            VIRRegistrationOutcome.CONFLICT if rejected.outcome == RunnerOutcome.CONFLICT
            else VIRRegistrationOutcome.AUTHORITY_REJECTION
        )
        return VIRRegistrationResult(outcome=mapped_outcome, detail=f"admission outcome was {rejected.outcome!r}: {rejected.detail}")

    if was_replay:
        return _existing_registration_result(execution_id)

    extra_provenance = {}
    if clarifies_execution_id is not None:
        extra_provenance["clarifies_execution_id"] = str(clarifies_execution_id)
    if clarifies_resolution_id is not None:
        extra_provenance["clarifies_resolution_id"] = clarifies_resolution_id

    # No VIR call here — this is the entire point of the repair. The
    # already-obtained `vir_resolution` is the authoritative result to
    # register, persisted through the identical shared TX2 path Path A uses.
    return _persist_vir_resolution(
        execution_id=execution_id, asset_id=asset_id, vir_resolution=vir_resolution,
        resolver_version=resolver_version, authority=authority,
        extra_provenance=extra_provenance or None,
    )


def _existing_registration_result(execution_id: UUID) -> VIRRegistrationResult:
    """REQ-B6-036 replay: reconstructs the result from the already-
    persisted state of a prior, already-completed registration for this
    exact execution_id, rather than re-deriving anything. Unchanged by this
    repair; used by both Path A and Path B."""
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
    swallows the caller's failure to report its own. Unchanged by this
    repair."""
    try:
        with session_scope() as session:
            persist_runner_report(session, execution_id=execution_id, new_status="FAILED", authority=authority)
            session.commit()
    except Exception:  # noqa: BLE001 — best-effort only, never masks the original failure
        pass
    return VIRRegistrationResult(outcome=outcome, execution_id=execution_id, detail=detail)
