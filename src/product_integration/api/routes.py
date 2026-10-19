"""PI-05 — product API routes.

Every route delegates to PI-04 (or, for the two capabilities PI-04 itself
doesn't wrap -- contact-only creation/retrieval and VIR clarification --
directly to the existing CPL/PI-01 functions, per §6's explicit allowance:
"use existing CPL/product-integration read paths ... without duplicating
domain behavior"). No VIR/PGDR/Case domain logic is reimplemented here.

Every route requires an authenticated end user (router-level dependency)
and reaches only that user's objects (product_integration.auth.ownership);
an object of another user is answered exactly like a missing one.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import desc

from app.cpl.identity.authority import AuthorityContext, AuthorityDeniedError
from app.cpl.identity.contacts import get_contact
from app.cpl.identity.outcomes import OperationOutcome
from app.cpl.models.case import Case
from app.cpl.models.runner_artifact import RunnerArtifact
from app.cpl.models.runner_execution import RunnerExecution
from app.db.engine import SessionLocal, session_scope

from pgdr.models import Answer, Consent, InitialComplaint, UserContext
from pgdr.session_controller import SessionController
from vir.domain.models import (
    ClarificationRequest as VIRClarificationRequest,
    ClarificationAnswer as VIRClarificationAnswer,
    VehicleIdentityRequest as RealVIRRequest,
    ManualIdentityInput,
    RegistrationInput,
    ConsentInput as VIRConsentInput,
)

from product_integration.cpl_registration import VIRRegistrationOutcome, register_vir_execution, register_vir_resolution_result
from product_integration.orchestration.case_orchestration import (
    DiagnosticStartOutcome,
    RegistrationOutcome,
    continue_vehicle_diagnostic,
    register_vehicle_for_contact,
    resolve_vehicle_identity,
    start_vehicle_diagnostic,
)
# _sync_case_with_execution is PI-04's own internal Case-sync primitive
# (honest-failure, single-transaction, exception-safe -- PI-04-VF-01).
# Reused directly here for the clarification route specifically because
# PI-04 has no public wrapper for VIR clarification at all (it only wraps
# fresh resolution, §9's Path A) -- re-implementing the identical
# current_execution_id + status-transition logic here would be exactly the
# kind of duplicate Case state machine §16 forbids. This is intra-package
# reuse of product_integration's own module, not a new mechanism.
from product_integration.orchestration.case_orchestration import _sync_case_with_execution
from product_integration.pgdr.session_adapter import PGDRSessionOutcome
from product_integration.vir.client import VIRClient
from product_integration.vir.errors import VIRClientError, VIRTechnicalFailureError
from product_integration.vir.presentation import build_view, redact_identifiers
from vir.domain.driver_confirmation import CONFIRMABLE_FIELDS

from product_integration.api.deps import get_authority, get_media_storage, get_pgdr_registry, get_principal, get_vir_client
from product_integration.auth.accounts import Principal
from product_integration.auth.ownership import (
    can_use_asset, not_found, owned_case, owned_execution, owns_media, record_media_owner, scoped_key,
)
from product_integration.media.storage import LocalMediaStorage, MediaValidationError
from product_integration.api.errors import ProductAPIError, ProductAPIErrorCategory
from product_integration.api.registry import PGDRSessionRegistry
from product_integration.api.schemas import (
    ArtifactResponse,
    CaseHistoryResponse,
    CaseStatusResponse,
    CaseListEntry,
    CaseListResponse,
    CaseVIRResponse,
    ContactResponse,
    DiagnosticQuestionSchema,
    DiagnosticResponse,
    DriverConfirmationCorrectionRequest,
    DriverConfirmationRequest,
    ExecutionStatusResponse,
    HistoryExecutionEntry,
    MediaUploadResponse,
    RegisterVehicleRequest,
    RegisterVehicleResponse,
    StartCaseRequest,
    StartDiagnosticRequest,
    SubmitAnswerRequest,
    SubmitClarificationRequest,
    VIRResolutionView,
)

router = APIRouter(dependencies=[Depends(get_principal)])


# -- contacts (§8) -------------------------------------------------------

# Contacts are created with their account by the operator command
# (product_integration.auth.cli), never through a web request.

@router.get("/contacts/{contact_id}", response_model=ContactResponse)
def get_contact_route(
    contact_id: UUID, authority: AuthorityContext = Depends(get_authority), principal: Principal = Depends(get_principal),
):
    if contact_id != principal.contact_id:
        raise not_found()
    with session_scope() as session:
        result = get_contact(session, contact_id, authority=authority)
        if result.outcome != OperationOutcome.SUCCESS:
            raise not_found()
        session.commit()
        return ContactResponse(contact_id=contact_id)


# -- vehicles (§9) -------------------------------------------------------

@router.post("/vehicles", response_model=RegisterVehicleResponse, status_code=201)
def register_vehicle_route(
    body: RegisterVehicleRequest, authority: AuthorityContext = Depends(get_authority),
    principal: Principal = Depends(get_principal),
):
    # The vehicle is always registered for the authenticated user's own
    # Contact, recorded as its OWNER; a contact named in the body is only
    # accepted when it is that same Contact.
    if body.existing_contact_id is not None and body.existing_contact_id != principal.contact_id:
        raise not_found()
    asset_key = scoped_key(principal, body.asset_idempotency_key)
    result = register_vehicle_for_contact(
        existing_contact_id=principal.contact_id, asset_domain=body.asset_domain, asset_type=body.asset_type,
        authority=authority, contact_idempotency_key=scoped_key(principal, body.contact_idempotency_key),
        asset_idempotency_key=asset_key, owner_relationship_idempotency_key=asset_key + "-owner",
    )
    if result.outcome != RegistrationOutcome.SUCCESS:
        category = (
            ProductAPIErrorCategory.AUTHORITY_REJECTION if result.outcome == RegistrationOutcome.AUTHORITY_REJECTION
            else ProductAPIErrorCategory.CONFLICT if result.outcome == RegistrationOutcome.CONFLICT
            else ProductAPIErrorCategory.NOT_FOUND if result.outcome == RegistrationOutcome.NOT_FOUND
            else ProductAPIErrorCategory.CPL_PERSISTENCE_FAILURE
        )
        raise ProductAPIError(category, result.detail or result.outcome, extra={"contact_id": str(result.contact_id) if result.contact_id else None})
    return RegisterVehicleResponse(outcome=result.outcome, contact_id=result.contact_id, asset_id=result.asset_id)


# -- case + VIR (§10/§11) -------------------------------------------------------

def _build_real_vir_request(body: StartCaseRequest) -> RealVIRRequest:
    kwargs: dict = {"request_id": body.request_id, "consent": VIRConsentInput(external_lookup_allowed=body.consent.external_lookup_allowed)}
    if body.vin:
        kwargs["vin"] = body.vin
    # VIR V1 (request_validation.py): the registration country is the one the
    # user chose, required for a VIN as for a plate, never defaulted here.
    if body.registration_number or body.registration_country_code:
        kwargs["registration"] = RegistrationInput(registration_number=body.registration_number, country_code=body.registration_country_code)
    if body.manufacturer or body.model:
        kwargs["manual_identity"] = ManualIdentityInput(manufacturer=body.manufacturer, model=body.model)
    return RealVIRRequest(**kwargs)


@router.get("/cases", response_model=CaseListResponse)
def list_cases_route(principal: Principal = Depends(get_principal)):
    with session_scope() as session:
        cases = (
            session.query(Case).filter(Case.primary_contact_id == principal.contact_id)
            .order_by(desc(Case.created_at)).limit(200).all()
        )
        return CaseListResponse(cases=[
            CaseListEntry(case_id=c.case_id, case_status=c.case_status, asset_id=c.asset_id,
                          created_at=c.created_at.isoformat() if c.created_at else None)
            for c in cases
        ])


@router.post("/cases", response_model=CaseVIRResponse, status_code=201)
async def start_case_route(
    body: StartCaseRequest, authority: AuthorityContext = Depends(get_authority),
    vir_client: VIRClient = Depends(get_vir_client), principal: Principal = Depends(get_principal),
):
    if body.contact_id != principal.contact_id:
        raise not_found()
    with session_scope() as session:
        if not can_use_asset(session, principal, body.asset_id):
            raise not_found()
    # A plate or a VIN leaves PI only for VIR, only with the explicit consent
    # to the external lookup and an explicitly chosen country; otherwise
    # nothing is created and VIR is not called. The refusal echoes nothing.
    if body.vin or body.registration_number:
        if not body.consent.external_lookup_allowed:
            raise ProductAPIError(ProductAPIErrorCategory.CONSENT_REQUIRED,
                                  "consent to the external lookup is required for a plate or a VIN")
        if not body.registration_country_code:
            raise ProductAPIError(ProductAPIErrorCategory.INVALID_REQUEST,
                                  "the registration country must be chosen explicitly")
    from product_integration.vir.schemas import VehicleIdentityRequest as ProductVIRRequest, ConsentInput as ProductConsentInput
    product_request_kwargs: dict = {"request_id": scoped_key(principal, body.request_id), "consent": ProductConsentInput(external_lookup_allowed=body.consent.external_lookup_allowed)}
    if body.vin:
        product_request_kwargs["vin"] = body.vin
    if body.registration_number or body.registration_country_code:
        product_request_kwargs["registration"] = {"registration_number": body.registration_number, "country_code": body.registration_country_code}
    if body.manufacturer or body.model:
        product_request_kwargs["manual_identity"] = {"manufacturer": body.manufacturer, "model": body.model}
    vir_request = ProductVIRRequest(**product_request_kwargs)

    result = await resolve_vehicle_identity(
        contact_id=body.contact_id, asset_id=body.asset_id, vir_client=vir_client, vir_request=vir_request,
        authority=authority, case_idempotency_key=scoped_key(principal, body.case_idempotency_key),
    )
    return CaseVIRResponse(
        outcome=result.outcome, contact_id=result.contact_id, asset_id=result.asset_id, case_id=result.case_id,
        vir_execution_id=result.vir_execution_id, vir_artifact_id=result.vir_artifact_id,
        vir_resolution_status=result.cpl_resolution_status, detail=result.detail,
    )


def _find_vir_execution_and_artifact(session, case_id: UUID) -> tuple[RunnerExecution, RunnerArtifact]:
    vir_execution = (
        session.query(RunnerExecution)
        .filter(RunnerExecution.case_id == case_id, RunnerExecution.runner_type == "VIR")
        .order_by(desc(RunnerExecution.created_at))
        .first()
    )
    if vir_execution is None:
        raise ProductAPIError(ProductAPIErrorCategory.NOT_FOUND, f"no VIR resolution found for case {case_id}")
    vir_artifact = (
        session.query(RunnerArtifact)
        .filter(RunnerArtifact.execution_id == vir_execution.execution_id, RunnerArtifact.artifact_type == "vir_resolution")
        .order_by(desc(RunnerArtifact.created_at))
        .first()
    )
    if vir_artifact is None:
        raise ProductAPIError(ProductAPIErrorCategory.NOT_FOUND, f"no VIR artifact found for case {case_id}")
    return vir_execution, vir_artifact


@router.post("/cases/{case_id}/vir/clarifications", response_model=CaseVIRResponse)
async def submit_clarification_route(
    case_id: UUID, body: SubmitClarificationRequest, authority: AuthorityContext = Depends(get_authority),
    vir_client: VIRClient = Depends(get_vir_client), principal: Principal = Depends(get_principal),
):
    """§12/§38: uses PI-01's already-repaired clarification path
    (register_vir_resolution_result, Path B) directly -- no second
    clarification mechanism, no fresh duplicate VIR resolve."""
    with session_scope() as session:
        case = owned_case(session, principal, case_id)
        vir_execution, vir_artifact = _find_vir_execution_and_artifact(session, case_id)
        original_resolution_id = vir_artifact.payload.get("resolution_id")
        asked = {q.get("question_id") for q in vir_artifact.payload.get("clarification_questions") or []
                 if isinstance(q, dict)}
        asset_id = case.asset_id

    # Only answers to questions VIR actually asked for this resolution: VIR
    # would silently ignore any other answer and resolve again (consulting
    # the providers), so PI refuses it first -- no VIR call, nothing written.
    if not body.answers or any(a.question_id not in asked for a in body.answers):
        raise ProductAPIError(ProductAPIErrorCategory.CLARIFICATION_REFUSED,
                              "answer only the questions asked for this vehicle", extra={"case_id": str(case_id)})

    # VIR V1 refuses an answer it cannot apply (VIR-ERR-016, resolution left
    # unchanged): a typed VIR failure for the product, nothing recorded here.
    try:
        clarified = await vir_client.submit_clarification(
            original_resolution_id,
            VIRClarificationRequest(answers=[VIRClarificationAnswer(question_id=a.question_id, value=a.value) for a in body.answers]),
        )
    except VIRTechnicalFailureError as exc:
        raise ProductAPIError(
            ProductAPIErrorCategory.VIR_TECHNICAL_FAILURE, str(exc),
            extra={"case_id": str(case_id), "vir_error_code": exc.error_code, "recoverable": exc.recoverable},
        ) from None
    except VIRClientError as exc:
        raise ProductAPIError(
            ProductAPIErrorCategory.VIR_TECHNICAL_FAILURE, type(exc).__name__, extra={"case_id": str(case_id)},
        ) from None

    vir_result = register_vir_resolution_result(
        vir_resolution=clarified, case_id=case_id, asset_id=asset_id, authority=authority,
        clarifies_execution_id=vir_execution.execution_id, clarifies_resolution_id=original_resolution_id,
    )
    if vir_result.outcome == VIRRegistrationOutcome.SUCCESS:
        sync_error = _sync_case_with_execution(
            case_id=case_id, execution_id=vir_result.execution_id, target_status="IN_PROGRESS", authority=authority,
            observed_status_label=vir_result.outcome,
        )
        if sync_error is not None:
            raise ProductAPIError(
                ProductAPIErrorCategory.CASE_ORCHESTRATION_FAILURE,
                f"clarified VIR resolution persisted correctly, but Case sync failed: {sync_error.underlying_error}",
                extra={"case_id": str(case_id), "vir_execution_id": str(vir_result.execution_id)},
            )

    return CaseVIRResponse(
        outcome=vir_result.outcome, asset_id=asset_id, case_id=case_id, vir_execution_id=vir_result.execution_id,
        vir_artifact_id=vir_result.artifact_id, vir_resolution_status=vir_result.cpl_resolution_status, detail=vir_result.detail,
    )


# -- VIR result and driver confirmation -------------------------------------------------------

def _has_diagnostic(session, case_id: UUID) -> bool:
    return session.query(RunnerExecution.execution_id).filter(
        RunnerExecution.case_id == case_id, RunnerExecution.runner_type == "PGDR").first() is not None


def _vir_refusal(exc: VIRClientError, case_id: UUID) -> ProductAPIError:
    """A value VIR refuses is the user's to fix (422, VIR's error code, never
    the value nor VIR's message); anything else is a VIR failure (502)."""
    if isinstance(exc, VIRTechnicalFailureError) and exc.http_status in (409, 422):
        return ProductAPIError(ProductAPIErrorCategory.VIR_INPUT_REFUSED, "VIR did not accept this value",
                               extra={"case_id": str(case_id), "vir_error_code": exc.error_code})
    return ProductAPIError(ProductAPIErrorCategory.VIR_TECHNICAL_FAILURE, type(exc).__name__,
                           extra={"case_id": str(case_id)})


@router.get("/cases/{case_id}/vir", response_model=VIRResolutionView)
async def get_case_vir_route(
    case_id: UUID, vir_client: VIRClient = Depends(get_vir_client), principal: Principal = Depends(get_principal),
):
    """The case's latest VIR result, read again from VIR (its stored result:
    no provider is consulted). The resolution is the one recorded for this
    case of this user, never one named by the client."""
    with session_scope() as session:
        owned_case(session, principal, case_id)
        vir_execution, vir_artifact = _find_vir_execution_and_artifact(session, case_id)
        resolution_id = vir_artifact.payload.get("resolution_id")
        locked = _has_diagnostic(session, case_id)
    try:
        document = await vir_client.get_resolution_document(resolution_id)
    except VIRClientError as exc:
        raise _vir_refusal(exc, case_id) from None
    return VIRResolutionView(case_id=case_id, vir_execution_id=vir_execution.execution_id,
                             **build_view(document, confirmations_locked=locked))


async def _driver_confirmation(case_id: UUID, field_path: str, operation: str, call, authority, principal) -> CaseVIRResponse:
    """confirm / correct / withdraw: ownership of the case and of its latest
    resolution checked first, the field must be one of VIR's seven, the
    identity is frozen once a diagnostic exists. VIR recomputes from its
    stored evidence (no provider call); the new state is registered in CPL
    as a new VIR execution of the same case."""
    if field_path not in CONFIRMABLE_FIELDS:
        with session_scope() as session:
            owned_case(session, principal, case_id)
        raise ProductAPIError(ProductAPIErrorCategory.INVALID_REQUEST, "this field cannot be confirmed",
                              extra={"case_id": str(case_id)})
    with session_scope() as session:
        case = owned_case(session, principal, case_id)
        vir_execution, vir_artifact = _find_vir_execution_and_artifact(session, case_id)
        resolution_id = vir_artifact.payload.get("resolution_id")
        asset_id = case.asset_id
        if _has_diagnostic(session, case_id):
            raise ProductAPIError(ProductAPIErrorCategory.CONFLICT,
                                  "the vehicle identity can no longer change once a diagnostic has started",
                                  extra={"case_id": str(case_id)})
    try:
        updated = await call(resolution_id)
    except VIRClientError as exc:
        raise _vir_refusal(exc, case_id) from None

    vir_result = register_vir_resolution_result(
        vir_resolution=updated, case_id=case_id, asset_id=asset_id, authority=authority,
        driver_confirmation={"operation": operation, "field_path": field_path,
                             "updates_execution_id": str(vir_execution.execution_id)},
    )
    if vir_result.outcome == VIRRegistrationOutcome.SUCCESS:
        sync_error = _sync_case_with_execution(
            case_id=case_id, execution_id=vir_result.execution_id, target_status="IN_PROGRESS", authority=authority,
            observed_status_label=vir_result.outcome,
        )
        if sync_error is not None:
            raise ProductAPIError(
                ProductAPIErrorCategory.CASE_ORCHESTRATION_FAILURE,
                f"VIR result persisted correctly, but Case sync failed: {sync_error.underlying_error}",
                extra={"case_id": str(case_id), "vir_execution_id": str(vir_result.execution_id)},
            )
    return CaseVIRResponse(
        outcome=vir_result.outcome, asset_id=asset_id, case_id=case_id, vir_execution_id=vir_result.execution_id,
        vir_artifact_id=vir_result.artifact_id, vir_resolution_status=vir_result.cpl_resolution_status,
        detail=vir_result.detail,
    )


@router.post("/cases/{case_id}/vir/confirmations", response_model=CaseVIRResponse)
async def confirm_vir_field_route(
    case_id: UUID, body: DriverConfirmationRequest, authority: AuthorityContext = Depends(get_authority),
    vir_client: VIRClient = Depends(get_vir_client), principal: Principal = Depends(get_principal),
):
    return await _driver_confirmation(
        case_id, body.field_path, "confirm",
        lambda resolution_id: vir_client.confirm_field(resolution_id, body.field_path, body.value), authority, principal)


@router.put("/cases/{case_id}/vir/confirmations/{field_path}", response_model=CaseVIRResponse)
async def correct_vir_field_route(
    case_id: UUID, field_path: str, body: DriverConfirmationCorrectionRequest,
    authority: AuthorityContext = Depends(get_authority), vir_client: VIRClient = Depends(get_vir_client),
    principal: Principal = Depends(get_principal),
):
    return await _driver_confirmation(
        case_id, field_path, "correct",
        lambda resolution_id: vir_client.correct_field(resolution_id, field_path, body.value), authority, principal)


@router.delete("/cases/{case_id}/vir/confirmations/{field_path}", response_model=CaseVIRResponse)
async def withdraw_vir_field_route(
    case_id: UUID, field_path: str, authority: AuthorityContext = Depends(get_authority),
    vir_client: VIRClient = Depends(get_vir_client), principal: Principal = Depends(get_principal),
):
    return await _driver_confirmation(
        case_id, field_path, "withdraw",
        lambda resolution_id: vir_client.withdraw_field(resolution_id, field_path), authority, principal)


# -- case status / history (§16/§18) -------------------------------------------------------

@router.get("/cases/{case_id}", response_model=CaseStatusResponse)
def get_case_route(case_id: UUID, principal: Principal = Depends(get_principal)):
    with session_scope() as session:
        case = owned_case(session, principal, case_id)
        return CaseStatusResponse(
            case_id=case.case_id, case_status=case.case_status, current_execution_id=case.current_execution_id,
            contact_id=case.primary_contact_id, asset_id=case.asset_id,
        )


@router.get("/cases/{case_id}/history", response_model=CaseHistoryResponse)
def get_case_history_route(case_id: UUID, principal: Principal = Depends(get_principal)):
    with session_scope() as session:
        case = owned_case(session, principal, case_id)
        executions = (
            session.query(RunnerExecution)
            .filter(RunnerExecution.case_id == case_id)
            .order_by(RunnerExecution.created_at)
            .all()
        )
        entries = []
        for execution in executions:
            artifact = (
                session.query(RunnerArtifact)
                .filter(RunnerArtifact.execution_id == execution.execution_id)
                .order_by(desc(RunnerArtifact.created_at))
                .first()
            )
            entries.append(HistoryExecutionEntry(
                execution_id=execution.execution_id, runner_type=execution.runner_type,
                execution_status=execution.execution_status, artifact_id=artifact.artifact_id if artifact else None,
            ))
        return CaseHistoryResponse(
            case_id=case.case_id, case_status=case.case_status, current_execution_id=case.current_execution_id,
            contact_id=case.primary_contact_id, asset_id=case.asset_id, executions=entries,
        )


# -- executions / artifacts (§15/§17) -------------------------------------------------------

@router.get("/executions/{execution_id}", response_model=ExecutionStatusResponse)
def get_execution_status_route(execution_id: UUID, principal: Principal = Depends(get_principal)):
    with session_scope() as session:
        execution = owned_execution(session, principal, execution_id)
        artifact = (
            session.query(RunnerArtifact)
            .filter(RunnerArtifact.execution_id == execution_id)
            .order_by(desc(RunnerArtifact.created_at))
            .first()
        )
        return ExecutionStatusResponse(
            execution_id=execution.execution_id, runner_type=execution.runner_type,
            execution_status=execution.execution_status, blocked=(execution.execution_status == "BLOCKED"),
            terminal=(execution.execution_status in ("COMPLETED", "FAILED", "CANCELLED")),
            updated_at=execution.updated_at.isoformat() if getattr(execution, "updated_at", None) else None,
            artifact_id=artifact.artifact_id if artifact else None,
        )


@router.get("/executions/{execution_id}/artifact", response_model=ArtifactResponse)
def get_execution_artifact_route(execution_id: UUID, principal: Principal = Depends(get_principal)):
    with session_scope() as session:
        owned_execution(session, principal, execution_id)
        artifact = (
            session.query(RunnerArtifact)
            .filter(RunnerArtifact.execution_id == execution_id)
            .order_by(desc(RunnerArtifact.created_at))
            .first()
        )
        if artifact is None:
            raise ProductAPIError(ProductAPIErrorCategory.NOT_FOUND, f"no artifact found for execution {execution_id}")
        payload = dict(artifact.payload)
        if artifact.artifact_type == "vir_resolution":
            payload = redact_identifiers(payload)   # the plate and the VIN are never served back
        return ArtifactResponse(
            artifact_id=artifact.artifact_id, execution_id=artifact.execution_id, artifact_type=artifact.artifact_type,
            artifact_status=artifact.artifact_status, payload=payload,
        )


# -- diagnostics (PGDR) (§13/§14) -------------------------------------------------------

_DIAGNOSTIC_FAILURE_CATEGORY = {
    "AUTHORITY_REJECTION": ProductAPIErrorCategory.AUTHORITY_REJECTION,
    "CONFLICT": ProductAPIErrorCategory.CONFLICT,
    "PGDR_TECHNICAL_FAILURE": ProductAPIErrorCategory.PGDR_TECHNICAL_FAILURE,
    "CPL_PERSISTENCE_FAILURE": ProductAPIErrorCategory.CPL_PERSISTENCE_FAILURE,
    "CASE_ORCHESTRATION_FAILURE": ProductAPIErrorCategory.CASE_ORCHESTRATION_FAILURE,
}


def _raise_if_diagnostic_failure(result, case_id: UUID) -> None:
    """§21/§22/§26: PI-03/PI-04's own genuine failure outcomes must map to
    their documented HTTP status via ProductAPIError -- never silently
    fall through as an HTTP 200 success. BLOCKED/COMPLETED/
    PI02_HANDOFF_REFUSED are all valid, non-error product responses (§23/
    §24/§25) and are NOT in this mapping on purpose."""
    category = _DIAGNOSTIC_FAILURE_CATEGORY.get(result.outcome)
    if category is not None:
        raise ProductAPIError(
            category, result.detail or result.outcome,
            extra={"case_id": str(case_id), "execution_id": str(result.pgdr_execution_id) if result.pgdr_execution_id else None},
        )


def _to_question_schema(q) -> DiagnosticQuestionSchema:
    return DiagnosticQuestionSchema(question_id=q.question_id, prompt=q.prompt, choices=list(q.choices) if q.choices else None)


def _diagnostic_response(result, case_id: UUID) -> DiagnosticResponse:
    if result.outcome == PGDRSessionOutcome.BLOCKED:
        blocked, terminal = True, False
    elif result.outcome == PGDRSessionOutcome.COMPLETED:
        blocked, terminal = False, True
    else:
        blocked, terminal = False, False
    return DiagnosticResponse(
        outcome=result.outcome, case_id=case_id, execution_id=result.pgdr_execution_id, blocked=blocked, terminal=terminal,
        pending_questions=[_to_question_schema(q) for q in (result.pending_questions or [])],
        artifact_id=result.pgdr_artifact_id, detail=result.detail,
        primary_diagnostic_media_reference=getattr(result, "primary_diagnostic_media_reference", None),
    )


@router.post("/media", response_model=MediaUploadResponse, status_code=201)
async def upload_media_route(
    file: UploadFile = File(...),
    media_storage: LocalMediaStorage = Depends(get_media_storage),
    principal: Principal = Depends(get_principal),
) -> MediaUploadResponse:
    """Block B1.5 — the real media-ingress boundary. Accepts an actual
    uploaded image (multipart/form-data), never an arbitrary string
    pretending one exists. `media_id` returned here is the only value a
    client subsequently uses as StartDiagnosticRequest.primary_
    diagnostic_media_reference -- always opaque, always server-generated,
    never a filesystem path or anything the client could construct
    itself. This endpoint is intentionally the same one a future mobile
    client would call (real HTTP multipart upload) -- not a desktop-
    specific filesystem mechanism."""
    content = await file.read()
    try:
        media_id = media_storage.store(content, file.content_type or "")
    except MediaValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with session_scope() as session:
        record_media_owner(session, principal, media_id)
        session.commit()
    return MediaUploadResponse(media_id=media_id)


@router.post("/cases/{case_id}/diagnostics", response_model=DiagnosticResponse)
async def start_diagnostic_route(
    case_id: UUID, body: StartDiagnosticRequest, response: Response, authority: AuthorityContext = Depends(get_authority),
    registry: PGDRSessionRegistry = Depends(get_pgdr_registry), principal: Principal = Depends(get_principal),
):
    with session_scope() as session:
        owned_case(session, principal, case_id)
        # Only media this user uploaded; any other reference is unknown.
        if body.primary_diagnostic_media_reference is not None and not owns_media(
            session, principal, body.primary_diagnostic_media_reference,
        ):
            raise not_found()
    session_controller = SessionController()
    result = await start_vehicle_diagnostic(
        case_id=case_id, session_controller=session_controller,
        # Block A repair note: complaint_text is optional; PGDR's own
        # InitialComplaint.free_text remains a required str (PGDR itself
        # is untouched by Block A). Falling back to "" here is a
        # TEMPORARY_COMPATIBILITY_MECHANISM (Block A; unchanged by Block
        # B1 per B1 §14 — not redesigned, not promoted to canonical). It
        # exists
        # solely because PGDR has no other entry point yet, not because
        # an empty complaint is the canonical Photo-First input model.
        # Block B (Dashboard Interpretation) is expected to replace this
        # with a real PGDR-side entry point that accepts primary
        # diagnostic media directly, at which point this fallback should
        # be removed rather than extended.
        initial_complaint=InitialComplaint(free_text=body.complaint_text or ""), user_context=UserContext(),
        consent=Consent(media_analysis_allowed=body.consent_media_analysis_allowed, report_storage_allowed=body.consent_report_storage_allowed),
        authority=authority,
        primary_diagnostic_media_reference=body.primary_diagnostic_media_reference,
    )
    if result.pgdr_execution_id is not None and result.pgdr_session is not None:
        registry.put(result.pgdr_execution_id, session_controller, result.pgdr_session)
    if result.outcome == DiagnosticStartOutcome.CASE_NOT_FOUND:
        raise ProductAPIError(ProductAPIErrorCategory.NOT_FOUND, f"case {case_id} not found")
    _raise_if_diagnostic_failure(result, case_id)
    # §22: only outcomes that actually create a PGDR execution are 201;
    # refusal creates nothing, so it is a normal 200 informative response.
    response.status_code = 201 if result.outcome in (PGDRSessionOutcome.BLOCKED, PGDRSessionOutcome.COMPLETED) else 200
    return _diagnostic_response(result, case_id)


@router.post("/cases/{case_id}/diagnostics/{execution_id}/answers", response_model=DiagnosticResponse)
async def submit_answer_route(
    case_id: UUID, execution_id: UUID, body: SubmitAnswerRequest, authority: AuthorityContext = Depends(get_authority),
    registry: PGDRSessionRegistry = Depends(get_pgdr_registry), principal: Principal = Depends(get_principal),
):
    # §31 resource-consistency check: the case must be the user's own, and
    # the execution must genuinely belong to it, before anything else
    # happens; any mismatch is answered like a missing object.
    with session_scope() as session:
        owned_case(session, principal, case_id)
        execution = session.get(RunnerExecution, execution_id)
        if execution is None or execution.case_id != case_id:
            raise not_found()

    entry = registry.get(execution_id)
    if entry is None:
        # §28/§46: the known PGDR cross-instance limitation, surfaced
        # honestly -- never silently started fresh, never fabricated.
        raise ProductAPIError(
            ProductAPIErrorCategory.PROCESS_LOCAL_STATE_UNAVAILABLE,
            f"no process-local PGDR session found for execution {execution_id} -- the PGDR SessionController "
            f"that started this diagnostic session no longer has in-memory state available (known PGDR "
            f"cross-instance limitation; see docs/build/PI_05_PRODUCT_API_CANDIDATE_EVIDENCE_v0.md)",
            extra={"case_id": str(case_id), "execution_id": str(execution_id)},
        )

    result = await continue_vehicle_diagnostic(
        case_id=case_id, execution_id=execution_id, session_controller=entry.session_controller,
        pgdr_session=entry.pgdr_session, answer=Answer(question_id=body.question_id, value=body.value),
        authority=authority,
    )
    if result.pgdr_session is not None:
        registry.put(execution_id, entry.session_controller, result.pgdr_session)
    else:
        registry.drop(execution_id)
    _raise_if_diagnostic_failure(result, case_id)
    return _diagnostic_response(result, case_id)
