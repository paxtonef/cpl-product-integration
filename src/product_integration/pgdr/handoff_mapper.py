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

    unresolved_fields = list(dc.get("unresolved_fields", []))

    # diagnostic_constraints only ever carries a boolean has_contradictions
    # flag on this path (confirmed directly against VIR's HandoffBuilder
    # source) — never fabricated into a synthetic per-item list.
    contradictions: list[str] = []

    return _build_pgdr_context(
        resolution_id=context.resolution_id, pgdr_status=pgdr_status,
        vehicle_identity=context.vehicle, confidence=confidence,
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

    contradictions = [_flatten_contradiction(c) for c in resolution.contradictions]

    return _build_pgdr_context(
        resolution_id=resolution.resolution_id, pgdr_status=pgdr_status,
        vehicle_identity=vehicle_identity, confidence=confidence,
        unresolved_fields=list(resolution.unresolved_fields), contradictions=contradictions,
    )
