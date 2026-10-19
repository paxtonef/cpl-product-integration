"""PI-02 — VIR -> PGDR Handoff Mapper.

A pure, deterministic, side-effect-free contract translation from VIR's real
domain objects to PGDR's real input contract. No I/O, no persistence, no
HTTP, no CPL involvement. Two entry points, both converging on the same
private constructor (`_build_pgdr_context`) so there is no duplicate
PGDR-object-construction logic anywhere in this module:

  map_diagnostic_context(context: DiagnosticIdentityContext)
      -> pgdr.models.VehicleIdentityContext
    The primary path. Confirmed by direct source inspection of VIR's
    HandoffBuilder (src/vir/application/build_handoff.py, pinned baseline
    a342aba7cc2fc517621f4fc79c3191bdfdc9e10b): `diagnostic_constraints`
    carries `confidence_score` (float) and `confidence_level` (already a
    plain string — VIR's own HandoffBuilder writes
    `resolution.confidence.level.value`) and `unresolved_fields` (a real
    list[str], not fabricated) — these are genuine data present on
    DiagnosticIdentityContext, not merely available on the richer object,
    correcting a looser phrasing in the Reality Check's own §14 ("DERIVABLE
    ... even though DiagnosticIdentityContext doesn't carry it directly" —
    the actual data does flow through `diagnostic_constraints`, just
    nested rather than top-level). `contradictions` is the one field this
    path genuinely cannot populate beyond an empty list: VIR's HandoffBuilder
    only writes a `has_contradictions` BOOLEAN into diagnostic_constraints,
    never the underlying per-contradiction detail — so this path always
    produces `contradictions=[]`, never fabricated from the boolean.

  map_resolution(resolution: VehicleIdentityResolution)
      -> pgdr.models.VehicleIdentityContext
    The richer path (PI-02 instruction §12/§20), used when full contradiction
    detail is needed. `resolution.contradictions` (list[Contradiction], each
    with field_path/values/severity/resolution_action) is flattened to
    `field_path` strings — the same "which fields" pattern PGDR's own
    `unresolved_fields: list[str]` already uses, and the single most stable,
    identifying piece of information per contradiction. `severity`,
    `values`, and `resolution_action` are NOT preserved in the flattened
    string: PGDR's own contract fixes `contradictions: list[str]`, so this
    information loss is inherent to PGDR's schema, not a choice this mapper
    makes to discard data casually — it is disclosed here and in the
    candidate evidence, not silently absorbed.

Both status-mapping paths share `_map_status`, the single place the
VIR-status -> PGDR-status admissibility rule is implemented.
"""
from __future__ import annotations

from typing import Optional

from pgdr.enums import ResolutionStatus as PGDRResolutionStatus
from pgdr.models import ConfidenceScore as PGDRConfidenceScore
from pgdr.models import VehicleIdentityContext as PGDRVehicleIdentityContext
from vir.domain.driver_confirmation import CONFIRMABLE_FIELDS, USER_CONFIRMED, epistemic_status
from vir.domain.enums import ResolutionStatus as VIRResolutionStatus
from vir.domain.models import Contradiction as VIRContradiction
from vir.domain.models import DiagnosticIdentityContext as VIRDiagnosticIdentityContext
from vir.domain.models import VehicleIdentityResolution as VIRVehicleIdentityResolution

from product_integration.pgdr.errors import VIRPGDRHandoffError

# --- Derived, not hard-coded (§9 of the PI-02 instruction) ----------------
# The admissibility rule is computed directly from the two real enum
# classes at import time, not asserted from this instruction's own prose.
# If a future VIR or PGDR change breaks the subset relationship this module
# depends on, importing this module itself fails loudly (AssertionError)
# rather than silently mismapping — this is the "must fail if a ninth VIR
# status is later added without mapper review" requirement (§17),
# enforced structurally, not only by a test.
_VIR_STATUS_VALUES = frozenset(s.value for s in VIRResolutionStatus)
_PGDR_STATUS_VALUES = frozenset(s.value for s in PGDRResolutionStatus)
_REFUSED_VIR_STATUS_VALUES = _VIR_STATUS_VALUES - _PGDR_STATUS_VALUES

assert len(_VIR_STATUS_VALUES) == 8, f"VIR ResolutionStatus no longer has 8 values: {sorted(_VIR_STATUS_VALUES)}"
assert len(_PGDR_STATUS_VALUES) == 5, f"PGDR ResolutionStatus no longer has 5 values: {sorted(_PGDR_STATUS_VALUES)}"
assert _PGDR_STATUS_VALUES <= _VIR_STATUS_VALUES, (
    "PGDR's admissible ResolutionStatus values are no longer a strict subset of VIR's — "
    "this is CONTRACT_DRIFT and this mapper must not be used until re-reviewed. "
    f"PGDR-only values: {sorted(_PGDR_STATUS_VALUES - _VIR_STATUS_VALUES)}"
)
assert len(_REFUSED_VIR_STATUS_VALUES) == 3, f"Expected exactly 3 refused VIR-only statuses, got: {sorted(_REFUSED_VIR_STATUS_VALUES)}"


# --- What PGDR receives: an explicit whitelist (preparation for production,
# block 4) --------------------------------------------------------------------
# Technical characteristics only, unknown values (None) included, plus VIR's
# own provenance flags. Never the vehicle identifiers (plate, VIN,
# registration country: CanonicalVehicleIdentity.identifiers) nor the
# registration-document date (first_registration_date): PGDR's diagnostic
# and applicability logic does not read them (pgdr 7b863c0 --
# VehicleApplicabilityContext.from_pgdr_vehicle_identity_dict always sets
# first_registration_date=None; the identity is otherwise only spread into
# MachineIdentityContext.attributes). The objects stay linked through the
# opaque VIR resolution_id. A new field reaches PGDR only by being added here.
PGDR_VEHICLE_IDENTITY_FIELDS: dict[str, Optional[tuple[str, ...]]] = {
    "manufacturer": None, "brand": None, "model": None, "generation": None, "variant": None, "trim": None,
    "production": ("year", "start_date", "end_date"),
    "body": ("type", "door_count"),
    "fuel": ("primary_type",),
    "engine": ("commercial_name", "engine_code", "displacement_cc", "cylinders", "power_kw", "power_hp"),
    "transmission": ("type", "gears"),
    "drivetrain": None, "version": None, "model_year": None, "cluster_type": None,
    "simulated": None, "user_declared": None,
}
# The flat keys of VIR's DiagnosticIdentityContext.vehicle (VIR's
# VEHICLE_FIELD_PATHS), less first_registration_date.
PGDR_DIAGNOSTIC_CONTEXT_FIELDS = (
    "manufacturer", "model", "production_year", "fuel_type", "engine_name", "power_kw", "generation", "version",
    "model_year", "cluster_type", "transmission_type", "engine_code", "transmission_gears", "drivetrain",
)


_WITHHELD_ROOTS = frozenset({"identifiers", "first_registration_date"})


def _whitelisted_identity(dumped: dict) -> dict:
    """Copies only PGDR_VEHICLE_IDENTITY_FIELDS (and, for a nested group,
    only its listed sub-fields) from a dumped CanonicalVehicleIdentity."""
    kept: dict = {}
    for key, sub_fields in PGDR_VEHICLE_IDENTITY_FIELDS.items():
        if key not in dumped:
            continue
        value = dumped[key]
        if sub_fields is not None and isinstance(value, dict):
            value = {sub: value.get(sub) for sub in sub_fields}
        kept[key] = value
    return kept


def _about_withheld_field(path: str) -> bool:
    """A field path naming a field PGDR never receives (identifiers,
    first_registration_date): not reported to PGDR as unresolved or
    contradictory, since PGDR has no such field."""
    return path.replace("[", ".").split(".", 1)[0] in _WITHHELD_ROOTS


def _map_status(vir_status: VIRResolutionStatus) -> PGDRResolutionStatus:
    """The single implementation of the admissibility rule (§8/§9). Raises
    VIRPGDRHandoffError for exactly the 3 VIR-only statuses; never
    translates, downgrades, promotes, or guesses."""
    if vir_status.value in _REFUSED_VIR_STATUS_VALUES:
        raise VIRPGDRHandoffError(vir_status.value, admissible_statuses=_PGDR_STATUS_VALUES)
    return PGDRResolutionStatus(vir_status.value)


def _flatten_contradiction(contradiction: VIRContradiction) -> str:
    """Flattens one VIR Contradiction to its field_path — the stable,
    identifying string PGDR's list[str] contract can hold. severity/values/
    resolution_action are not representable in a single string under
    PGDR's own fixed schema; see this module's docstring."""
    return contradiction.field_path


def _build_pgdr_context(
    *, resolution_id: str, pgdr_status: PGDRResolutionStatus,
    vehicle_identity: Optional[dict], confidence: Optional[PGDRConfidenceScore],
    unresolved_fields: list[str], contradictions: list[str],
) -> PGDRVehicleIdentityContext:
    """The single PGDR-object construction point both public entry points
    use — no duplicate construction logic anywhere in this module. This is
    an actual pgdr.models.VehicleIdentityContext instance; Pydantic
    validation runs here, on construction — success means the object is
    genuinely valid, not merely dict-shaped like one (§11)."""
    return PGDRVehicleIdentityContext(
        resolution_id=resolution_id,
        resolution_status=pgdr_status,
        confidence=confidence,
        vehicle_identity=vehicle_identity,
        unresolved_fields=unresolved_fields,
        contradictions=contradictions,
    )


def _confirmation_only_fields(resolution: VIRVehicleIdentityResolution) -> list[str]:
    """VIR V1: the fields whose retained value rests on a driver confirmation
    alone (VIR's own epistemic_status == "user_confirmed": no decode nor
    qualified provider behind it). PGDR's contract has no provenance slot, so
    such a value cannot be handed on without reading as known."""
    evidence = {fe.field_path: fe for fe in resolution.field_evidence}
    return sorted(
        path for path in CONFIRMABLE_FIELDS
        if path in evidence and epistemic_status(evidence[path].sources, evidence[path].resolved_value) == USER_CONFIRMED
    )


def _withhold(vehicle_identity: dict, path: str) -> None:
    """Sets one dotted path of the dumped identity to None (unknown)."""
    *parents, leaf = path.split(".")
    node = vehicle_identity
    for key in parents:
        node = node.get(key)
        if not isinstance(node, dict):
            return
    if leaf in node:
        node[leaf] = None


def map_diagnostic_context(context: VIRDiagnosticIdentityContext) -> PGDRVehicleIdentityContext:
    """Primary path (§5/§12). Pure, deterministic, no I/O. Raises
    VIRPGDRHandoffError if `context.identity_status` is one of the 3
    VIR-only statuses."""
    pgdr_status = _map_status(context.identity_status)

    dc = context.diagnostic_constraints
    confidence: Optional[PGDRConfidenceScore] = None
    if "confidence_score" in dc and "confidence_level" in dc:
        # confidence_level is already a plain string in diagnostic_constraints
        # (VIR's own HandoffBuilder writes `.value`, not the enum member) —
        # a DIRECT pass-through, not a transform, once extracted from the dict.
        confidence = PGDRConfidenceScore(score=dc["confidence_score"], level=dc["confidence_level"])

    unresolved_fields = [f for f in dc.get("unresolved_fields", []) if not _about_withheld_field(f)]
    vehicle = {key: context.vehicle[key] for key in PGDR_DIAGNOSTIC_CONTEXT_FIELDS if key in context.vehicle}

    # diagnostic_constraints only ever carries a boolean has_contradictions
    # flag on this path (confirmed directly against VIR's HandoffBuilder
    # source) — never fabricated into a synthetic per-item list.
    contradictions: list[str] = []

    return _build_pgdr_context(
        resolution_id=context.resolution_id, pgdr_status=pgdr_status,
        vehicle_identity=vehicle, confidence=confidence,
        unresolved_fields=unresolved_fields, contradictions=contradictions,
    )


def map_resolution(resolution: VIRVehicleIdentityResolution) -> PGDRVehicleIdentityContext:
    """Richer path (§12/§20): full confidence object and real
    per-contradiction detail, both genuinely available only on
    VehicleIdentityResolution. Pure, deterministic, no I/O. Raises
    VIRPGDRHandoffError if `resolution.resolution_status` is one of the 3
    VIR-only statuses."""
    pgdr_status = _map_status(resolution.resolution_status)

    confidence = PGDRConfidenceScore(score=resolution.confidence.score, level=resolution.confidence.level.value)

    vehicle_identity = (
        resolution.vehicle_identity.model_dump(mode="json") if resolution.vehicle_identity is not None else None
    )

    # VIR V1 driver confirmations: a value resting on a confirmation alone is
    # never handed to PGDR as a known value (it is not a decode); PGDR sees it
    # as unknown. Status (VIR already caps it at provisionally_resolved) and
    # every decoded or concordantly-confirmed value are unchanged.
    unresolved_fields = list(resolution.unresolved_fields)
    if vehicle_identity is not None:
        for path in _confirmation_only_fields(resolution):
            _withhold(vehicle_identity, path)
            if path not in unresolved_fields:
                unresolved_fields.append(path)
        vehicle_identity = _whitelisted_identity(vehicle_identity)
    unresolved_fields = [f for f in unresolved_fields if not _about_withheld_field(f)]

    contradictions = [
        _flatten_contradiction(c) for c in resolution.contradictions if not _about_withheld_field(c.field_path)
    ]

    return _build_pgdr_context(
        resolution_id=resolution.resolution_id, pgdr_status=pgdr_status,
        vehicle_identity=vehicle_identity, confidence=confidence,
        unresolved_fields=unresolved_fields, contradictions=contradictions,
    )
