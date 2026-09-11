"""PI-04 — Case Orchestration Service.

The actual product entry point: sequences PI-01 (VIR) then PI-02 (handoff
mapping) then PI-03 (PGDR) under one governed CPL Case, per the shape already
named by CPL's own `app/automotive/orchestration/__init__.py` placeholder.
This module fills that placeholder in, composing PI-01/PI-02/PI-03 in full —
none of their internal logic is duplicated here.

Case status mapping (derived from CPL's own frozen `VALID_CASE_STATUSES`
— `OPEN, IN_PROGRESS, WAITING_FOR_USER, WAITING_FOR_EXTERNAL_INFORMATION,
RESOLVED, CLOSED, REOPENED, CANCELLED` — read directly from
`app/cpl/cases/lifecycle.py`; no status is invented):

  create_case()                    -> OPEN            (CPL's own default)
  VIR execution admitted                -> IN_PROGRESS
  PI-02 refuses the VIR handoff             -> WAITING_FOR_EXTERNAL_INFORMATION
                                                (the case is not abandoned —
                                                it genuinely needs different/
                                                better identity information
                                                before it can proceed, which
                                                is exactly what this status
                                                already means; never CANCELLED,
                                                which would wrongly imply a
                                                deliberate stop)
  PGDR BLOCKED (awaiting a user answer)         -> WAITING_FOR_USER
  PGDR resumes (submit_answer)                      -> IN_PROGRESS
  PGDR terminal (COMPLETED or ESCALATED)                -> RESOLVED
  A PGDR_TECHNICAL_FAILURE (e.g. PI-03's disclosed          -> Case status left
    cross-controller limitation) is NOT a Case-level             UNCHANGED —
    status transition — it's an adapter invocation failure,       this is an
    not a governed domain observation about the case               adapter/
    itself, so no CPL status write is attempted for it              integration
                                                                      failure, not
                                                                       a Case
                                                                        observation

Case.current_execution_id is treated strictly as an opaque Case-side pointer
(§13) — set to the VIR execution after VIR admission, then to the PGDR
execution once PGDR starts. It is never read as if it carried execution
semantics of its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from sqlalchemy import desc

from app.cpl.identity.authority import Authority, AuthorityContext, AuthorityDeniedError
from app.cpl.identity.contacts import create_contact, get_contact
from app.cpl.identity.outcomes import OperationOutcome
from app.cpl.assets.authority import AssetAuthority
from app.cpl.assets.creation import create_asset
from app.cpl.cases.authority import CaseAuthority
from app.cpl.cases.lifecycle import create_case, transition_case_status
from app.cpl.cases.outcomes import CaseOutcome
from app.cpl.models.case import Case
from app.cpl.models.runner_artifact import RunnerArtifact
from app.cpl.models.runner_execution import RunnerExecution
from app.db.engine import session_scope

from pgdr.models import Answer, Consent, InitialComplaint, PreGarageDiagnosticRequest, UserContext
from pgdr.session_controller import SessionController
from pgdr.models import DiagnosticSession
from vir.domain.models import VehicleIdentityResolution as VIRVehicleIdentityResolution

from product_integration.cpl_registration import VIRRegistrationOutcome, VIRRegistrationResult, register_vir_execution
from product_integration.orchestration.errors import CaseNotFoundError, VIRArtifactNotFoundError
from product_integration.pgdr.errors import VIRPGDRHandoffError
from product_integration.pgdr.handoff_mapper import map_resolution
from product_integration.pgdr.session_adapter import (
    PGDRAdapterResult,
    PGDRSessionOutcome,
    continue_pgdr_session,
    start_pgdr_session,
)
from product_integration.vir.client import VIRClient
from product_integration.vir.schemas import VehicleIdentityRequest

# CPL's own domain/case_type vocabulary is free text (no CHECK-constrained
# enum, confirmed by reading app/cpl/models/case.py directly) -- these are
# this product's own chosen values, not CPL-mandated ones.
CASE_DOMAIN = "AUTOMOTIVE"
CASE_TYPE = "VEHICLE_DIAGNOSTIC"


class RegistrationOutcome:
    SUCCESS = "SUCCESS"
    AUTHORITY_REJECTION = "AUTHORITY_REJECTION"
    CONFLICT = "CONFLICT"
    NOT_FOUND = "NOT_FOUND"
    CPL_PERSISTENCE_FAILURE = "CPL_PERSISTENCE_FAILURE"


class DiagnosticStartOutcome:
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    PI02_HANDOFF_REFUSED = "PI02_HANDOFF_REFUSED"
    VIR_ARTIFACT_NOT_FOUND = "VIR_ARTIFACT_NOT_FOUND"
    CASE_NOT_FOUND = "CASE_NOT_FOUND"
    AUTHORITY_REJECTION = "AUTHORITY_REJECTION"
    CONFLICT = "CONFLICT"
    PGDR_TECHNICAL_FAILURE = "PGDR_TECHNICAL_FAILURE"
    CPL_PERSISTENCE_FAILURE = "CPL_PERSISTENCE_FAILURE"


@dataclass
class RegistrationResult:
    outcome: str
    contact_id: Optional[UUID] = None
    asset_id: Optional[UUID] = None
    detail: Optional[str] = None


@dataclass
class VehicleIdentityResolutionResult:
    outcome: str  # a VIRRegistrationOutcome value, passed through directly (§ below)
    contact_id: Optional[UUID] = None
    asset_id: Optional[UUID] = None
    case_id: Optional[UUID] = None
    vir_execution_id: Optional[UUID] = None
    vir_artifact_id: Optional[UUID] = None
    cpl_resolution_status: Optional[str] = None
    detail: Optional[str] = None


@dataclass
class DiagnosticStartResult:
    outcome: str
    case_id: Optional[UUID] = None
    pgdr_execution_id: Optional[UUID] = None
    pgdr_session: Optional[DiagnosticSession] = None  # caller must retain (PI-03's own disclosed limitation)
    pending_questions: list = field(default_factory=list)
    pgdr_artifact_id: Optional[UUID] = None
    detail: Optional[str] = None


@dataclass
class DiagnosticContinueResult:
    outcome: str
    case_id: Optional[UUID] = None
    pgdr_execution_id: Optional[UUID] = None
    pgdr_session: Optional[DiagnosticSession] = None
    pending_questions: list = field(default_factory=list)
    pgdr_artifact_id: Optional[UUID] = None
    detail: Optional[str] = None


def register_vehicle_for_contact(
    *,
    contact_type: str = "PERSON",
    display_name: Optional[str] = None,
    asset_domain: str,
    asset_type: str,
    authority: AuthorityContext,
    contact_idempotency_key: str,
    asset_idempotency_key: str,
    existing_contact_id: Optional[UUID] = None,
) -> RegistrationResult:
    """§8: ensure a product user/contact has a registered vehicle
    represented in CPL. No VIR resolution happens here (§8 — identity
    resolution is `resolve_vehicle_identity`'s own, separate concern);
    this function only establishes the Contact and Asset CPL already knows
    how to create, reused verbatim, not reimplemented.

    If `existing_contact_id` is supplied, it is looked up via `get_contact`
    rather than creating a new Contact — a Contact may register multiple
    vehicles, and a vehicle may be diagnosed multiple times, so this
    function is deliberately reusable rather than tied to a single Case."""
    with session_scope() as session:
        try:
            if existing_contact_id is not None:
                contact_result = get_contact(session, existing_contact_id, authority=authority)
                if contact_result.outcome != OperationOutcome.SUCCESS:
                    session.commit()
                    return RegistrationResult(
                        outcome=RegistrationOutcome.NOT_FOUND, detail=f"existing_contact_id lookup: {contact_result.outcome!r}",
                    )
                contact_id = contact_result.object_id
            else:
                contact_result = create_contact(
                    session, contact_type=contact_type, display_name=display_name,
                    authority=authority, idempotency_key=contact_idempotency_key,
                )
                if contact_result.outcome != OperationOutcome.SUCCESS:
                    session.commit()
                    return RegistrationResult(
                        outcome=_map_operation_outcome(contact_result.outcome),
                        detail=f"create_contact outcome {contact_result.outcome!r}: {contact_result.detail}",
                    )
                contact_id = contact_result.object_id

            asset_result = create_asset(
                session, asset_domain=asset_domain, asset_type=asset_type,
                authority=authority, idempotency_key=asset_idempotency_key,
            )
        except AuthorityDeniedError as exc:
            # create_contact/get_contact/create_asset all call
            # authority.require(...) unconditionally and let
            # AuthorityDeniedError propagate as a raw exception (confirmed
            # by direct source read — unlike B6's runner layer, B3/B4's
            # identity/asset layer does not catch and wrap it into a typed
            # outcome) — caught here, at the one place PI-04 owns, and
            # translated into this orchestration's own typed result.
            session.rollback()
            return RegistrationResult(outcome=RegistrationOutcome.AUTHORITY_REJECTION, detail=str(exc))

        if asset_result.outcome != OperationOutcome.SUCCESS:
            session.rollback()
            return RegistrationResult(
                outcome=_map_operation_outcome(asset_result.outcome),
                contact_id=contact_id,
                detail=f"create_asset outcome {asset_result.outcome!r}: {asset_result.detail}",
            )
        session.commit()
        return RegistrationResult(outcome=RegistrationOutcome.SUCCESS, contact_id=contact_id, asset_id=asset_result.object_id)


async def resolve_vehicle_identity(
    *,
    contact_id: UUID,
    asset_id: UUID,
    vir_client: VIRClient,
    vir_request: VehicleIdentityRequest,
    authority: AuthorityContext,
    case_idempotency_key: str,
    resolver_version: str = "unknown",
) -> VehicleIdentityResolutionResult:
    """§9: run the complete PI-01 VIR integration for the registered
    vehicle, under a freshly-created (or replayed) Case. PI-01's own
    outcome vocabulary is passed straight through in `.outcome` — never
    re-wrapped or reinterpreted, so a caller inspecting a
    VehicleIdentityResolutionResult sees exactly the same distinctions
    PI-01 itself already guarantees (§21's failure-boundary requirement,
    satisfied by reuse rather than re-derivation)."""
    with session_scope() as session:
        try:
            case_result = create_case(
                session, primary_contact_id=contact_id, asset_id=asset_id, domain=CASE_DOMAIN, case_type=CASE_TYPE,
                authority=authority, idempotency_key=case_idempotency_key,
            )
        except AuthorityDeniedError as exc:
            session.rollback()
            return VehicleIdentityResolutionResult(
                outcome=VIRRegistrationOutcome.AUTHORITY_REJECTION, contact_id=contact_id, asset_id=asset_id,
                detail=str(exc),
            )
        if case_result.outcome != CaseOutcome.SUCCESS:
            session.commit()
            return VehicleIdentityResolutionResult(
                outcome=_map_case_outcome(case_result.outcome), contact_id=contact_id, asset_id=asset_id,
                detail=f"create_case outcome {case_result.outcome!r}: {case_result.detail}",
            )
        case_id = case_result.object_id
        session.commit()

    vir_result: VIRRegistrationResult = await register_vir_execution(
        vir_client=vir_client, case_id=case_id, asset_id=asset_id, vir_request=vir_request,
        authority=authority, resolver_version=resolver_version,
    )

    if vir_result.outcome == VIRRegistrationOutcome.SUCCESS:
        _set_current_execution(case_id, vir_result.execution_id)
        _transition_case(case_id, "IN_PROGRESS", authority=authority,
                          idempotency_key=f"case-transition:{case_id}:IN_PROGRESS:{vir_result.execution_id}")

    return VehicleIdentityResolutionResult(
        outcome=vir_result.outcome, contact_id=contact_id, asset_id=asset_id, case_id=case_id,
        vir_execution_id=vir_result.execution_id, vir_artifact_id=vir_result.artifact_id,
        cpl_resolution_status=vir_result.cpl_resolution_status, detail=vir_result.detail,
    )


async def start_vehicle_diagnostic(
    *,
    case_id: UUID,
    session_controller: SessionController,
    initial_complaint: InitialComplaint,
    user_context: UserContext,
    consent: Consent,
    authority: AuthorityContext,
    resolver_version: str = "unknown",
) -> DiagnosticStartResult:
    """§10/§15/§16: start PGDR under the same Case, only after the VIR
    identity handoff is admissible. `initial_complaint`/`user_context`/
    `consent` are USER-ORIGINATED (§6's boundary — never derived from VIR
    data anywhere in this function)."""
    with session_scope() as session:
        case = session.get(Case, case_id)
        if case is None:
            return DiagnosticStartResult(outcome=DiagnosticStartOutcome.CASE_NOT_FOUND, case_id=case_id)
        asset_id = case.asset_id

        vir_execution = (
            session.query(RunnerExecution)
            .filter(RunnerExecution.case_id == case_id, RunnerExecution.runner_type == "VIR")
            .order_by(desc(RunnerExecution.created_at))
            .first()
        )
        if vir_execution is None:
            raise VIRArtifactNotFoundError(case_id)
        vir_artifact = (
            session.query(RunnerArtifact)
            .filter(RunnerArtifact.execution_id == vir_execution.execution_id, RunnerArtifact.artifact_type == "vir_resolution")
            .order_by(desc(RunnerArtifact.created_at))
            .first()
        )
        if vir_artifact is None:
            raise VIRArtifactNotFoundError(case_id)
        vir_payload = dict(vir_artifact.payload)
        vir_artifact_id = vir_artifact.artifact_id

    # §15's exact §14 reuse: reconstruct the real VIR VehicleIdentityResolution
    # from the durable, governed artifact payload (not a live VIR round-trip)
    # and use PI-02's richer map_resolution() path -- this is genuinely the
    # same VIR object PI-01 persisted, not an approximation.
    vir_resolution = VIRVehicleIdentityResolution.model_validate(vir_payload)

    try:
        vehicle_identity_context = map_resolution(vir_resolution)
    except VIRPGDRHandoffError as exc:
        # §16: PI-02 refusal -- do NOT start PGDR. Preserve VIR's domain
        # truth: nothing about the VIR result is altered or reinterpreted;
        # the Case simply cannot proceed to PGDR with this identity result.
        _transition_case(case_id, "WAITING_FOR_EXTERNAL_INFORMATION", authority=authority,
                          idempotency_key=f"case-transition:{case_id}:WAITING_FOR_EXTERNAL_INFORMATION:{vir_execution.execution_id}")
        return DiagnosticStartResult(
            outcome=DiagnosticStartOutcome.PI02_HANDOFF_REFUSED, case_id=case_id,
            detail=f"PI-02 refused the VIR handoff: {exc}",
        )

    request = PreGarageDiagnosticRequest(
        request_id=f"PI04-{case_id}", vehicle_identity_context=vehicle_identity_context,
        initial_complaint=initial_complaint, user_context=user_context, consent=consent,
    )

    pgdr_result: PGDRAdapterResult = start_pgdr_session(
        session_controller=session_controller, request=request, case_id=case_id, asset_id=asset_id,
        vir_artifact_id=vir_artifact_id, authority=authority, resolver_version=resolver_version,
    )

    _apply_pgdr_case_transition(case_id, pgdr_result, authority)

    return DiagnosticStartResult(
        outcome=pgdr_result.outcome, case_id=case_id, pgdr_execution_id=pgdr_result.execution_id,
        pgdr_session=pgdr_result.session, pending_questions=pgdr_result.pending_questions,
        pgdr_artifact_id=pgdr_result.artifact_id, detail=pgdr_result.detail,
    )


async def continue_vehicle_diagnostic(
    *,
    case_id: UUID,
    execution_id: UUID,
    session_controller: SessionController,
    pgdr_session: DiagnosticSession,
    answer: Answer,
    authority: AuthorityContext,
) -> DiagnosticContinueResult:
    """§11: resume a PGDR diagnostic waiting for caller-supplied user
    input. Delegates entirely to PI-03 -- never fabricates an answer, never
    silently starts a new session on failure (§11's explicit prohibitions)."""
    with session_scope() as session:
        case = session.get(Case, case_id)
        if case is None:
            raise CaseNotFoundError(case_id)

    pgdr_result: PGDRAdapterResult = continue_pgdr_session(
        session_controller=session_controller, pgdr_session=pgdr_session, answer=answer,
        execution_id=execution_id, authority=authority,
    )

    _apply_pgdr_case_transition(case_id, pgdr_result, authority)

    return DiagnosticContinueResult(
        outcome=pgdr_result.outcome, case_id=case_id, pgdr_execution_id=pgdr_result.execution_id,
        pgdr_session=pgdr_result.session, pending_questions=pgdr_result.pending_questions,
        pgdr_artifact_id=pgdr_result.artifact_id, detail=pgdr_result.detail,
    )


# -- internal helpers -------------------------------------------------------

def _apply_pgdr_case_transition(case_id: UUID, pgdr_result: PGDRAdapterResult, authority: AuthorityContext) -> None:
    """§13/§17/§18: Case.current_execution_id sequencing + status
    transition, derived from the PGDR outcome. A PGDR_TECHNICAL_FAILURE or
    CPL_PERSISTENCE_FAILURE deliberately does NOT trigger a Case status
    write here (module docstring) -- only genuine BLOCKED/COMPLETED
    domain-observable outcomes do."""
    if pgdr_result.outcome == PGDRSessionOutcome.BLOCKED:
        _set_current_execution(case_id, pgdr_result.execution_id)
        _transition_case(case_id, "WAITING_FOR_USER", authority=authority,
                          idempotency_key=f"case-transition:{case_id}:WAITING_FOR_USER:{pgdr_result.execution_id}")
    elif pgdr_result.outcome == PGDRSessionOutcome.COMPLETED:
        _set_current_execution(case_id, pgdr_result.execution_id)
        _transition_case(case_id, "RESOLVED", authority=authority,
                          idempotency_key=f"case-transition:{case_id}:RESOLVED:{pgdr_result.execution_id}")
    # AUTHORITY_REJECTION/CONFLICT/PGDR_TECHNICAL_FAILURE/CPL_PERSISTENCE_FAILURE:
    # no Case-level write -- these are adapter/authority-layer outcomes, not
    # governed domain observations about the Case itself.


def _set_current_execution(case_id: UUID, execution_id: Optional[UUID]) -> None:
    if execution_id is None:
        return
    with session_scope() as session:
        case = session.get(Case, case_id)
        if case is not None:
            case.current_execution_id = execution_id
            session.commit()


def _transition_case(case_id: UUID, new_status: str, *, authority: AuthorityContext, idempotency_key: str) -> None:
    with session_scope() as session:
        transition_case_status(
            session, case_id=case_id, new_status=new_status, authority=authority, idempotency_key=idempotency_key,
        )
        session.commit()


def _map_operation_outcome(outcome: str) -> str:
    """Maps app.cpl.identity.outcomes.OperationOutcome's real values
    (SUCCESS, NOT_FOUND, REJECTED, INVALID, CONFLICTING, ALREADY_EXISTS —
    confirmed by direct source read; this is NOT the same vocabulary as
    RunnerOutcome/CaseOutcome, which use AUTHORITY_REJECTION/CONFLICT)."""
    if outcome == OperationOutcome.NOT_FOUND:
        return RegistrationOutcome.NOT_FOUND
    if outcome == OperationOutcome.CONFLICTING:
        return RegistrationOutcome.CONFLICT
    return RegistrationOutcome.CPL_PERSISTENCE_FAILURE


def _map_case_outcome(outcome: str) -> str:
    if outcome == CaseOutcome.CONFLICT:
        return VIRRegistrationOutcome.CONFLICT
    return VIRRegistrationOutcome.CPL_PERSISTENCE_FAILURE
