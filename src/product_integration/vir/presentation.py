"""The VIR result as the product shows it to the vehicle's owner.

Built from VIR's own JSON document (GET /v1/vehicle-identities/{id}),
validated with VIR's own model, and read with VIR's own rules
(vir.domain.driver_confirmation, vir.application.driver_confirmation): the
per-field epistemic status, which source supports the retained value, the
values the sources propose for the seven confirmable fields. PI adds no
rule, no status, no confidence and no value of its own.

Kept apart, as VIR keeps them: the normalized fields (with their sources and
the sources giving another value), the unknown fields, the contradictions,
the alternative and set-aside candidates, and the providers' descriptive
information (never an identity field).

The vehicle's identifiers (plate, VIN) never leave PI through this view:
every "identifiers.*" path is left out and no candidate identity is copied.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from vir.application.driver_confirmation import proposed_values
from vir.domain.driver_confirmation import (
    CONFIRMABLE_FIELDS, EPISTEMIC_LABELS, epistemic_status, get_path, supports_value,
)
from vir.domain.enums import ProvenanceMethod
from vir.domain.models import VehicleIdentityResolution

IDENTIFIER_PREFIX = "identifiers"
_IDENTIFIER_KEYS = ("vin", "registration_number")


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _is_identifier(field_path: str) -> bool:
    return field_path == IDENTIFIER_PREFIX or field_path.startswith(IDENTIFIER_PREFIX + ".")


def _status(sources, value) -> dict:
    status = epistemic_status(sources, value)
    return {"status": status, "status_label": EPISTEMIC_LABELS.get(status)}


def _is_own_confirmation_of_another_value(source, value) -> bool:
    return source.method == ProvenanceMethod.USER_CONFIRMATION and not supports_value(source, value)


def _source(source) -> dict:
    return {
        "source_id": source.source_id, "method": _plain(source.method), "role": source.role,
        "reliability": source.reliability, "simulated": source.simulated, "partial": source.partial,
        "user_declared": source.user_declared,
    }


def _divergent(source) -> dict:
    value = source.source_value if source.source_value is not None else source.reported_value
    return {"source_id": source.source_id, "value": _plain(value), "method": _plain(source.method)}


def _field(fe) -> dict:
    """Retained value with the sources that support it; the sources giving
    another value (an alternative candidate, the driver's confirmation of
    another value) listed apart, never as the value's provenance."""
    retained = [s for s in fe.sources
                if s.role != "divergent" and not _is_own_confirmation_of_another_value(s, fe.resolved_value)]
    divergent = [s for s in fe.sources
                 if s.role == "divergent" or _is_own_confirmation_of_another_value(s, fe.resolved_value)]
    return {
        "field_path": fe.field_path, "value": _plain(fe.resolved_value), **_status(fe.sources, fe.resolved_value),
        "sources": [_source(s) for s in retained], "divergent": [_divergent(s) for s in divergent],
        "consulted_without_value": [s.source_id for s in fe.consulted_without_value],
    }


def _confirmation_entry(resolution: VehicleIdentityResolution, evidence: dict, path: str) -> dict:
    fe = evidence.get(path)
    value = get_path(resolution.vehicle_identity, path) if resolution.vehicle_identity is not None else None
    own = [s for s in (fe.sources if fe else []) if s.method == ProvenanceMethod.USER_CONFIRMATION]
    confirmation = None
    if own:
        given = own[0].source_value if own[0].source_value is not None else own[0].reported_value
        confirmation = {"value": _plain(given), "applied": path in resolution.user_confirmed_fields}
    kind = CONFIRMABLE_FIELDS[path]
    choices = ([m.value for m in kind if m.value != "unknown"] if isinstance(kind, type) and issubclass(kind, Enum)
               else None)
    return {
        "field_path": path, "value": _plain(value),
        **(_status(fe.sources, fe.resolved_value) if fe else {"status": None, "status_label": None}),
        "proposals": [{"value": _plain(v), "sources": list(src)} for v, src in proposed_values(resolution, path)],
        "confirmation": confirmation, "choices": choices, "input_type": "number" if kind is int else "text",
    }


def build_view(document: dict, *, confirmations_locked: bool = False) -> dict:
    resolution = VehicleIdentityResolution.model_validate(document)
    evidence = {fe.field_path: fe for fe in resolution.field_evidence}
    return {
        "resolution_status": _plain(resolution.resolution_status),
        "confidence": {"score": resolution.confidence.score, "level": _plain(resolution.confidence.level)},
        "simulated": resolution.simulated,
        "registration_country": resolution.registration_country,
        "exact_factory_configuration_known": resolution.exact_factory_configuration_known,
        "exact_factory_configuration_reasons": list(resolution.exact_factory_configuration_reasons),
        "fields": [_field(fe) for fe in resolution.field_evidence if not _is_identifier(fe.field_path)],
        "unknown_fields": [f for f in resolution.unresolved_fields if not _is_identifier(f)],
        "user_declared_fields": list(resolution.user_declared_fields),
        "user_confirmed_fields": list(resolution.user_confirmed_fields),
        "contradictions": [
            {"field_path": c.field_path, "severity": c.severity,
             "values": [{"source_id": v.source_id, "value": None if _is_identifier(c.field_path) else _plain(v.value)}
                        for v in c.values]}
            for c in resolution.contradictions
        ],
        "alternative_candidates": [
            {"candidate_id": c.candidate_id, "source_ids": list(c.source_ids), "candidate_score": c.candidate_score,
             "matching_fields": list(c.matching_fields), "conflicting_fields": list(c.conflicting_fields),
             "missing_fields": list(c.missing_fields)}
            for c in resolution.alternative_candidates
        ],
        "excluded_candidates": [
            {"field_path": x.field_path, "reason": x.reason, "reason_label": x.reason_label,
             "declared_value": None if _is_identifier(x.field_path) else _plain(x.declared_value),
             "candidate_value": None if _is_identifier(x.field_path) else _plain(x.candidate_value),
             "source_ids": list(x.candidate.source_ids), "declaration_verified": x.declaration_verified}
            for x in resolution.excluded_candidates
        ],
        "descriptive_info": [
            {"source_id": d.source_id, "provider_field": d.provider_field, "label": d.label, "value": d.value,
             "unit": d.unit, "simulated": d.simulated}
            for d in resolution.provider_descriptive_info
        ],
        "limitations": list(resolution.limitations),
        "clarification_questions": [
            {"question_id": q.question_id, "prompt": q.prompt, "question_type": q.question_type,
             "choices": [{"label": ch.label, "value": _plain(ch.value)} for ch in (q.choices or [])] or None}
            for q in resolution.clarification_questions
        ],
        "confirmations": [_confirmation_entry(resolution, evidence, path) for path in CONFIRMABLE_FIELDS],
        "confirmations_locked": confirmations_locked,
    }


def redact_identifiers(payload: dict) -> dict:
    """A stored VIR resolution payload without the plate and the VIN: the
    retained identity's and every candidate identity's identifiers, and the
    values of identifier evidence. Used before such a payload is served."""
    redacted = dict(payload)

    def scrub_identity(identity):
        if not isinstance(identity, dict):
            return identity
        identity = dict(identity)
        identifiers = dict(identity.get("identifiers") or {})
        for key in _IDENTIFIER_KEYS:
            if identifiers.get(key) is not None:
                identifiers[key] = None
        identity["identifiers"] = identifiers
        return identity

    redacted["vehicle_identity"] = scrub_identity(payload.get("vehicle_identity"))
    redacted["alternative_candidates"] = [
        {**c, "identity": scrub_identity(c.get("identity"))} if isinstance(c, dict) else c
        for c in payload.get("alternative_candidates") or []
    ]
    redacted["field_evidence"] = [
        fe for fe in payload.get("field_evidence") or []
        if not (isinstance(fe, dict) and _is_identifier(str(fe.get("field_path", ""))))
    ]
    redacted["contradictions"] = [
        {**c, "values": [{**v, "value": None} for v in c.get("values") or []]}
        if isinstance(c, dict) and _is_identifier(str(c.get("field_path", ""))) else c
        for c in payload.get("contradictions") or []
    ]
    return redacted

