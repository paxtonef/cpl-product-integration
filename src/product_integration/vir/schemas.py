"""Wire-contract schemas for the VIR HTTP API, independently defined here.

Per PI-01's own boundary rule: the integration point is VIR's public HTTP
API, not VIR's Python internals. These models mirror the JSON shapes VIR's
API actually serializes (`vir.domain.models`, `vir.api.schemas`, read
directly at VIR baseline a342aba7cc2fc517621f4fc79c3191bdfdc9e10b) without
importing vir's package — a genuine VIR schema change would break this
client at request/response validation time (a good thing: it fails loudly
rather than silently drifting), never by import-time coupling.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# --- Request models -----------------------------------------------------

class RegistrationInput(BaseModel):
    registration_number: Optional[str] = None
    country_code: Optional[str] = None


class ManualIdentityInput(BaseModel):
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    production_year: Optional[int] = None
    fuel_type: Optional[str] = None
    engine_displacement_cc: Optional[int] = None
    engine_power_kw: Optional[float] = None
    transmission_type: Optional[str] = None


class ConsentInput(BaseModel):
    external_lookup_allowed: bool


class VehicleIdentityRequest(BaseModel):
    request_id: str
    locale: str = "fr-FR"
    registration: RegistrationInput = Field(default_factory=RegistrationInput)
    vin: Optional[str] = None
    manual_identity: ManualIdentityInput = Field(default_factory=ManualIdentityInput)
    supporting_documents: list[Any] = Field(default_factory=list)
    consent: ConsentInput


class ClarificationAnswer(BaseModel):
    question_id: str
    value: Any


class ClarificationRequest(BaseModel):
    answers: list[ClarificationAnswer] = Field(default_factory=list)


# --- Response models ------------------------------------------------------

class Confidence(BaseModel):
    score: float = 0.0
    level: str = "unresolved"


class CanonicalVehicleIdentity(BaseModel):
    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    generation: Optional[str] = None
    variant: Optional[str] = None
    trim: Optional[str] = None
    production: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict)
    fuel: dict[str, Any] = Field(default_factory=dict)
    engine: dict[str, Any] = Field(default_factory=dict)
    transmission: dict[str, Any] = Field(default_factory=dict)
    drivetrain: Optional[str] = None
    identifiers: dict[str, Any] = Field(default_factory=dict)


class VehicleCandidate(BaseModel):
    candidate_id: str
    identity: CanonicalVehicleIdentity
    matching_fields: list[str] = Field(default_factory=list)
    conflicting_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    candidate_score: float = 0.0


class ContradictionValue(BaseModel):
    value: Any
    source_id: str


class Contradiction(BaseModel):
    contradiction_id: str
    field_path: str
    values: list[ContradictionValue] = Field(default_factory=list)
    severity: str
    resolution_action: str = "request_user_confirmation"


class ClarificationChoice(BaseModel):
    label: str
    value: Any


class ClarificationQuestion(BaseModel):
    question_id: str
    target_field: str
    reason: str
    question_type: str
    prompt: str
    choices: Optional[list[ClarificationChoice]] = None
    required: bool = True


class SourceEvidence(BaseModel):
    source_id: str
    reported_value: Any
    reliability: str


class FieldEvidence(BaseModel):
    field_path: str
    resolved_value: Any
    sources: list[SourceEvidence] = Field(default_factory=list)
    confidence: str = "medium"


class SourceSummary(BaseModel):
    source_id: str
    retrieved_at: datetime
    reliability: str
    fields_provided: list[str] = Field(default_factory=list)


class VehicleIdentityResolution(BaseModel):
    """Mirrors vir.domain.models.VehicleIdentityResolution's JSON shape
    exactly (field-for-field, read directly from source at the pinned
    baseline). PI-01 never imports that class — see module docstring."""
    request_id: str
    resolution_id: str
    created_at: datetime
    resolution_status: str  # one of VIR's 8 values — validated in status_mapping.py
    confidence: Confidence = Field(default_factory=Confidence)
    vehicle_identity: Optional[CanonicalVehicleIdentity] = None
    alternative_candidates: list[VehicleCandidate] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    clarification_questions: list[ClarificationQuestion] = Field(default_factory=list)
    field_evidence: list[FieldEvidence] = Field(default_factory=list)
    source_summary: list[SourceSummary] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class DiagnosticIdentityContext(BaseModel):
    """Mirrors vir.domain.models.DiagnosticIdentityContext's JSON shape."""
    resolution_id: str
    identity_status: str
    vehicle: dict[str, Any] = Field(default_factory=dict)
    diagnostic_constraints: dict[str, Any] = Field(default_factory=dict)


class VIRErrorResponse(BaseModel):
    """Mirrors the structured error body vir.api.routes's exception_handler
    produces for every VIRBaseError subclass."""
    error_code: str
    message: str
    recoverable: bool
