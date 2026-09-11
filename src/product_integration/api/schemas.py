"""PI-05 — product API request/response schemas.

§20: explicit Pydantic contracts only. Never a raw SQLAlchemy model, never a
raw internal PI-01/02/03/04 result object serialized as-is -- every response
here is constructed field-by-field from those internal results.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# -- contacts -----------------------------------------------------------

class CreateContactRequest(BaseModel):
    contact_type: str = "PERSON"
    display_name: Optional[str] = None
    idempotency_key: str


class ContactResponse(BaseModel):
    contact_id: UUID
    contact_type: Optional[str] = None
    display_name: Optional[str] = None


# -- vehicles -------------------------------------------------------------

class RegisterVehicleRequest(BaseModel):
    existing_contact_id: Optional[UUID] = None
    contact_type: str = "PERSON"
    display_name: Optional[str] = None
    asset_domain: str = "AUTOMOTIVE"
    asset_type: str = "PASSENGER_CAR"
    contact_idempotency_key: str
    asset_idempotency_key: str


class RegisterVehicleResponse(BaseModel):
    outcome: str
    contact_id: Optional[UUID] = None
    asset_id: Optional[UUID] = None
    detail: Optional[str] = None


# -- case / VIR -------------------------------------------------------------

class ConsentInputSchema(BaseModel):
    external_lookup_allowed: bool = False


class StartCaseRequest(BaseModel):
    """§10/§11: creates the governed Case and runs VIR identity resolution
    in one product operation -- matching PI-04's own `resolve_vehicle_
    identity` granularity exactly (it already couples Case creation with
    VIR admission), not inventing a separate Case-only creation step PI-04
    itself doesn't have."""
    contact_id: UUID
    asset_id: UUID
    request_id: str
    vin: Optional[str] = None
    registration_number: Optional[str] = None
    registration_country_code: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    consent: ConsentInputSchema = Field(default_factory=ConsentInputSchema)
    case_idempotency_key: str


class CaseVIRResponse(BaseModel):
    outcome: str
    contact_id: Optional[UUID] = None
    asset_id: Optional[UUID] = None
    case_id: Optional[UUID] = None
    vir_execution_id: Optional[UUID] = None
    vir_artifact_id: Optional[UUID] = None
    vir_resolution_status: Optional[str] = None
    detail: Optional[str] = None


class ClarificationAnswerSchema(BaseModel):
    question_id: str
    value: Any


class SubmitClarificationRequest(BaseModel):
    answers: list[ClarificationAnswerSchema]


# -- diagnostics (PGDR) -------------------------------------------------------------

class StartDiagnosticRequest(BaseModel):
    complaint_text: str
    consent_media_analysis_allowed: bool = False
    consent_report_storage_allowed: bool = False


class SubmitAnswerRequest(BaseModel):
    question_id: str
    value: Any


class DiagnosticQuestionSchema(BaseModel):
    question_id: str
    prompt: str
    choices: Optional[list[str]] = None


class DiagnosticResponse(BaseModel):
    outcome: str
    case_id: Optional[UUID] = None
    execution_id: Optional[UUID] = None
    blocked: bool = False
    terminal: bool = False
    pending_questions: list[DiagnosticQuestionSchema] = Field(default_factory=list)
    artifact_id: Optional[UUID] = None
    detail: Optional[str] = None


# -- execution status / case status ------------------------------------------

class ExecutionStatusResponse(BaseModel):
    execution_id: UUID
    runner_type: str
    execution_status: str
    blocked: bool
    terminal: bool
    updated_at: Optional[str] = None
    artifact_id: Optional[UUID] = None


class CaseStatusResponse(BaseModel):
    case_id: UUID
    case_status: str
    current_execution_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    asset_id: Optional[UUID] = None


# -- artifacts -------------------------------------------------------------

class ArtifactResponse(BaseModel):
    artifact_id: UUID
    execution_id: UUID
    artifact_type: str
    artifact_status: str
    payload: dict[str, Any]


# -- history -------------------------------------------------------------

class HistoryExecutionEntry(BaseModel):
    execution_id: UUID
    runner_type: str
    execution_status: str
    artifact_id: Optional[UUID] = None


class CaseHistoryResponse(BaseModel):
    case_id: UUID
    case_status: str
    current_execution_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    asset_id: Optional[UUID] = None
    executions: list[HistoryExecutionEntry] = Field(default_factory=list)
