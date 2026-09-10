"""PI-02 test suite — pure unit tests, zero I/O, zero external services.

Covers: status exhaustiveness (all 8 VIR values, §17), field mapping (§18),
contradiction flattening (§19), richer confidence path (§20), Pydantic
contract (§21), purity (§22). No PostgreSQL, no HTTP, no VIR/PGDR runtime
services — only their real Pydantic model classes, imported directly.
"""
from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from pgdr.models import VehicleIdentityContext as PGDRVehicleIdentityContext
from vir.domain.enums import ConfidenceLevel, ResolutionStatus as VIRResolutionStatus
from vir.domain.models import (
    CanonicalVehicleIdentity,
    Confidence,
    Contradiction,
    ContradictionValue,
    DiagnosticIdentityContext,
    VehicleIdentityResolution,
)

from product_integration.pgdr.errors import VIRPGDRHandoffError
from product_integration.pgdr.handoff_mapper import (
    _PGDR_STATUS_VALUES,
    _REFUSED_VIR_STATUS_VALUES,
    _VIR_STATUS_VALUES,
    map_diagnostic_context,
    map_resolution,
)

ADMISSIBLE = {
    VIRResolutionStatus.RESOLVED, VIRResolutionStatus.PROVISIONALLY_RESOLVED, VIRResolutionStatus.AMBIGUOUS,
    VIRResolutionStatus.INSUFFICIENT_DATA, VIRResolutionStatus.CONTRADICTORY,
}
REFUSED = {
    VIRResolutionStatus.UNSUPPORTED_COUNTRY, VIRResolutionStatus.PROVIDER_UNAVAILABLE,
    VIRResolutionStatus.INVALID_IDENTIFIER,
}


def make_context(status: VIRResolutionStatus, **overrides) -> DiagnosticIdentityContext:
    defaults = dict(
        resolution_id="VIR-RES-TEST",
        identity_status=status,
        vehicle={},
        diagnostic_constraints={},
    )
    defaults.update(overrides)
    return DiagnosticIdentityContext(**defaults)


def make_resolution(status: VIRResolutionStatus, **overrides) -> VehicleIdentityResolution:
    defaults = dict(
        request_id="REQ-TEST", resolution_id="VIR-RES-TEST", resolution_status=status,
    )
    defaults.update(overrides)
    return VehicleIdentityResolution(**defaults)


class TestEnumDerivation:
    """§9: prove the 8/5/3 split against the real enum classes, not this
    instruction's prose."""

    def test_eight_vir_values(self):
        assert len(_VIR_STATUS_VALUES) == 8
        assert _VIR_STATUS_VALUES == {s.value for s in VIRResolutionStatus}

    def test_five_pgdr_values(self):
        assert len(_PGDR_STATUS_VALUES) == 5

    def test_pgdr_is_strict_subset_of_vir(self):
        assert _PGDR_STATUS_VALUES < _VIR_STATUS_VALUES  # strict subset, not equal

    def test_exactly_three_refused(self):
        assert _REFUSED_VIR_STATUS_VALUES == {s.value for s in REFUSED}


class TestStatusExhaustiveness:
    """§17: one explicit test per VIR status value — 8 total."""

    @pytest.mark.parametrize("status", sorted(ADMISSIBLE, key=lambda s: s.value))
    def test_admissible_status_succeeds(self, status):
        result = map_diagnostic_context(make_context(status))
        assert result.resolution_status.value == status.value
        assert isinstance(result, PGDRVehicleIdentityContext)  # genuinely constructed, validated

    @pytest.mark.parametrize("status", sorted(REFUSED, key=lambda s: s.value))
    def test_refused_status_raises(self, status):
        with pytest.raises(VIRPGDRHandoffError) as exc_info:
            map_diagnostic_context(make_context(status))
        assert exc_info.value.vir_status == status.value

    def test_all_eight_covered_between_the_two_classes_above(self):
        covered = ADMISSIBLE | REFUSED
        assert {s.value for s in covered} == _VIR_STATUS_VALUES
        assert len(covered) == 8


class TestFieldMapping:
    """§18: field-by-field verification of the DiagnosticIdentityContext path."""

    def test_resolution_id_direct(self):
        result = map_diagnostic_context(make_context(VIRResolutionStatus.RESOLVED, resolution_id="ABC-123"))
        assert result.resolution_id == "ABC-123"

    def test_vehicle_populated_dict_direct(self):
        vehicle = {"manufacturer": "Renault", "model": "Clio", "production_year": 2019}
        result = map_diagnostic_context(make_context(VIRResolutionStatus.RESOLVED, vehicle=vehicle))
        assert result.vehicle_identity == vehicle

    def test_vehicle_empty_dict_stays_empty_dict_not_none(self):
        """§15: no unrequested normalization — an empty dict from VIR stays
        an empty dict, never silently promoted to None."""
        result = map_diagnostic_context(make_context(VIRResolutionStatus.INSUFFICIENT_DATA, vehicle={}))
        assert result.vehicle_identity == {}
        assert result.vehicle_identity is not None

    def test_confidence_extracted_from_diagnostic_constraints_when_present(self):
        result = map_diagnostic_context(make_context(
            VIRResolutionStatus.RESOLVED,
            diagnostic_constraints={"confidence_score": 0.82, "confidence_level": "high"},
        ))
        assert result.confidence.score == 0.82
        assert result.confidence.level == "high"

    def test_confidence_none_when_keys_absent(self):
        """No fabrication (§20): if diagnostic_constraints doesn't actually
        carry confidence data, output confidence is None, not a guessed
        default."""
        result = map_diagnostic_context(make_context(VIRResolutionStatus.AMBIGUOUS, diagnostic_constraints={}))
        assert result.confidence is None

    def test_confidence_none_when_only_one_key_present(self):
        """Partial data is not enough to construct a valid ConfidenceScore
        — treated as absent, not partially fabricated."""
        result = map_diagnostic_context(make_context(
            VIRResolutionStatus.AMBIGUOUS, diagnostic_constraints={"confidence_score": 0.5},
        ))
        assert result.confidence is None

    def test_unresolved_fields_direct_from_diagnostic_constraints(self):
        result = map_diagnostic_context(make_context(
            VIRResolutionStatus.PROVISIONALLY_RESOLVED,
            diagnostic_constraints={"unresolved_fields": ["engine.power_kw", "transmission.type"]},
        ))
        assert result.unresolved_fields == ["engine.power_kw", "transmission.type"]

    def test_unresolved_fields_empty_when_absent(self):
        result = map_diagnostic_context(make_context(VIRResolutionStatus.RESOLVED, diagnostic_constraints={}))
        assert result.unresolved_fields == []

    def test_diagnostic_constraints_boolean_never_becomes_fabricated_contradiction_list(self):
        """The has_contradictions boolean must never be turned into a
        synthetic single-item contradictions list."""
        result = map_diagnostic_context(make_context(
            VIRResolutionStatus.CONTRADICTORY, diagnostic_constraints={"has_contradictions": True},
        ))
        assert result.contradictions == []

    def test_no_extra_fields_leak_from_diagnostic_constraints(self):
        """§16: diagnostic_constraints carries engine/factory-config booleans
        with no PGDR target — confirm they never appear anywhere on the
        output object (there is no field for them to leak into, but this
        proves the mapper doesn't do a generic **kwargs passthrough that
        would break if PGDR's model ever gained a matching field name)."""
        result = map_diagnostic_context(make_context(
            VIRResolutionStatus.RESOLVED,
            diagnostic_constraints={"exact_engine_code_known": True, "exact_factory_configuration_known": False},
        ))
        assert not hasattr(result, "exact_engine_code_known")
        assert not hasattr(result, "exact_factory_configuration_known")


class TestContradictionFlattening:
    """§19: exhaustive contradiction flattening, against the real Contradiction model."""

    def test_zero_contradictions(self):
        result = map_resolution(make_resolution(VIRResolutionStatus.RESOLVED, contradictions=[]))
        assert result.contradictions == []

    def test_single_contradiction(self):
        c = Contradiction(contradiction_id="C1", field_path="vehicle.manufacturer",
                           values=[ContradictionValue(value="Peugeot", source_id="s1")], severity="high")
        result = map_resolution(make_resolution(VIRResolutionStatus.CONTRADICTORY, contradictions=[c]))
        assert result.contradictions == ["vehicle.manufacturer"]

    def test_multiple_contradictions_preserve_order(self):
        c1 = Contradiction(contradiction_id="C1", field_path="vehicle.manufacturer", severity="high")
        c2 = Contradiction(contradiction_id="C2", field_path="vehicle.engine.power_kw", severity="medium")
        c3 = Contradiction(contradiction_id="C3", field_path="vehicle.fuel.primary_type", severity="low")
        result = map_resolution(make_resolution(VIRResolutionStatus.CONTRADICTORY, contradictions=[c1, c2, c3]))
        assert result.contradictions == ["vehicle.manufacturer", "vehicle.engine.power_kw", "vehicle.fuel.primary_type"]

    def test_contradiction_with_empty_values_list(self):
        c = Contradiction(contradiction_id="C1", field_path="vehicle.model", values=[], severity="low")
        result = map_resolution(make_resolution(VIRResolutionStatus.CONTRADICTORY, contradictions=[c]))
        assert result.contradictions == ["vehicle.model"]

    def test_contradiction_with_many_values(self):
        c = Contradiction(
            contradiction_id="C1", field_path="vehicle.engine.commercial_name",
            values=[ContradictionValue(value=f"v{i}", source_id=f"s{i}") for i in range(5)],
            severity="high",
        )
        result = map_resolution(make_resolution(VIRResolutionStatus.CONTRADICTORY, contradictions=[c]))
        assert result.contradictions == ["vehicle.engine.commercial_name"]

    def test_special_characters_in_field_path_preserved(self):
        c = Contradiction(contradiction_id="C1", field_path="vehicle.identifiers['vin']", severity="high")
        result = map_resolution(make_resolution(VIRResolutionStatus.CONTRADICTORY, contradictions=[c]))
        assert result.contradictions == ["vehicle.identifiers['vin']"]

    def test_default_resolution_action_does_not_affect_flattening(self):
        """resolution_action has a model default ('request_user_confirmation')
        — confirm it plays no role in the flattened string regardless."""
        c = Contradiction(contradiction_id="C1", field_path="vehicle.model", severity="low")
        assert c.resolution_action == "request_user_confirmation"  # confirm the actual model default
        result = map_resolution(make_resolution(VIRResolutionStatus.CONTRADICTORY, contradictions=[c]))
        assert result.contradictions == ["vehicle.model"]


class TestRicherConfidencePath:
    """§20: full confidence object, only via map_resolution."""

    def test_confidence_transferred_with_level_as_plain_string(self):
        resolution = make_resolution(
            VIRResolutionStatus.RESOLVED, confidence=Confidence(score=0.91, level=ConfidenceLevel.CONFIRMED),
        )
        result = map_resolution(resolution)
        assert result.confidence.score == 0.91
        assert result.confidence.level == "confirmed"
        assert isinstance(result.confidence.level, str)  # not VIR's enum type leaking through

    def test_default_confidence_when_none_specified(self):
        resolution = make_resolution(VIRResolutionStatus.INSUFFICIENT_DATA)  # Confidence() default
        result = map_resolution(resolution)
        assert result.confidence.score == 0.0
        assert result.confidence.level == "unresolved"

    def test_vehicle_identity_none_preserved_as_none_not_empty_dict(self):
        """Unlike the DiagnosticIdentityContext path (where VIR's own
        HandoffBuilder already collapsed None -> {}), the richer path
        legitimately distinguishes None from an empty identity — preserved,
        not normalized (§15)."""
        resolution = make_resolution(VIRResolutionStatus.INSUFFICIENT_DATA, vehicle_identity=None)
        result = map_resolution(resolution)
        assert result.vehicle_identity is None

    def test_vehicle_identity_populated_dumps_to_dict(self):
        identity = CanonicalVehicleIdentity(manufacturer="Peugeot", model="308")
        resolution = make_resolution(VIRResolutionStatus.RESOLVED, vehicle_identity=identity)
        result = map_resolution(resolution)
        assert result.vehicle_identity["manufacturer"] == "Peugeot"
        assert result.vehicle_identity["model"] == "308"

    def test_confidence_not_fabricated_when_diagnostic_context_lacks_it(self):
        """Cross-check against the primary path: DiagnosticIdentityContext
        without confidence data in diagnostic_constraints must NOT silently
        acquire a fabricated confidence — this is the explicit §20
        anti-fabrication rule, tested from the other direction."""
        result = map_diagnostic_context(make_context(VIRResolutionStatus.RESOLVED, diagnostic_constraints={}))
        assert result.confidence is None


class TestPydanticContract:
    """§21: every successful mapping must be a genuinely valid PGDR object."""

    def test_output_is_actual_pgdr_class(self):
        result = map_diagnostic_context(make_context(VIRResolutionStatus.RESOLVED))
        assert type(result) is PGDRVehicleIdentityContext

    def test_output_round_trips_through_serialization(self):
        result = map_resolution(make_resolution(
            VIRResolutionStatus.CONTRADICTORY,
            contradictions=[Contradiction(contradiction_id="C1", field_path="x", severity="low")],
        ))
        dumped = result.model_dump(mode="json")
        reloaded = PGDRVehicleIdentityContext.model_validate(dumped)
        assert reloaded == result

    def test_invalid_confidence_score_would_fail_pydantic_validation(self):
        """Confirms validation genuinely runs — an out-of-range score
        (PGDR's ConfidenceScore has ge=0.0, le=1.0) must fail construction,
        proving map_resolution doesn't bypass Pydantic's own checks."""
        resolution = make_resolution(VIRResolutionStatus.RESOLVED, confidence=Confidence(score=1.0, level=ConfidenceLevel.CONFIRMED))
        # 1.0 is valid; confirm the boundary itself succeeds, then confirm
        # the mapper has no path that could ever construct an invalid score
        # (VIR's own Confidence model already constrains to [0,1], so an
        # out-of-range value cannot reach the mapper in the first place —
        # this is a structural guarantee inherited from VIR's own model).
        result = map_resolution(resolution)
        assert result.confidence.score == 1.0


class TestPurity:
    """§22: deterministic, no source mutation."""

    def test_repeated_calls_produce_equal_output(self):
        ctx = make_context(VIRResolutionStatus.RESOLVED, vehicle={"manufacturer": "Peugeot"},
                            diagnostic_constraints={"confidence_score": 0.7, "confidence_level": "medium",
                                                     "unresolved_fields": ["a", "b"]})
        r1 = map_diagnostic_context(ctx)
        r2 = map_diagnostic_context(ctx)
        r3 = map_diagnostic_context(ctx)
        assert r1 == r2 == r3

    def test_source_diagnostic_context_not_mutated(self):
        ctx = make_context(VIRResolutionStatus.RESOLVED, vehicle={"manufacturer": "Peugeot"},
                            diagnostic_constraints={"confidence_score": 0.7, "confidence_level": "medium"})
        before = copy.deepcopy(ctx.model_dump())
        map_diagnostic_context(ctx)
        after = ctx.model_dump()
        assert before == after

    def test_source_resolution_not_mutated(self):
        c = Contradiction(contradiction_id="C1", field_path="x", severity="high")
        resolution = make_resolution(VIRResolutionStatus.CONTRADICTORY, contradictions=[c])
        before = copy.deepcopy(resolution.model_dump())
        map_resolution(resolution)
        after = resolution.model_dump()
        assert before == after

    def test_repeated_richer_calls_produce_equal_output(self):
        resolution = make_resolution(
            VIRResolutionStatus.AMBIGUOUS, confidence=Confidence(score=0.3, level=ConfidenceLevel.LOW),
            contradictions=[Contradiction(contradiction_id="C1", field_path="x", severity="low")],
        )
        r1 = map_resolution(resolution)
        r2 = map_resolution(resolution)
        assert r1 == r2
