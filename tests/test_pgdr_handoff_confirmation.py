"""VIR V1 driver confirmation through the handoff PI actually uses.

VIR V1 lets a driver confirmation fill an empty identity field, with
provenance method "user_confirmation" — never a decode, never a provider
value (docs/CONFIRMATION_CONDUCTEUR.md). PGDR's VehicleIdentityContext has
no provenance slot, so PI-02's map_resolution() must not hand PGDR a value
supported by a confirmation alone as if it were known: such a field reaches
PGDR as unknown (None, listed in unresolved_fields). A decoded value, alone
or confirmed concordantly, is unchanged.

The second class drives the real chain: VIR's app (ASGI) -> PI-01 client and
mirror schema -> CPL artifact payload -> VIR model -> map_resolution(), so
the provenance must survive PI-01's mirror for the rule to apply.
Fictitious values only; no identifier value is asserted or printed."""
from __future__ import annotations

import httpx

from vir.domain.enums import ResolutionStatus as VIRResolutionStatus
from vir.domain.models import (
    CanonicalVehicleIdentity, Engine, FieldEvidence, SourceEvidence, VehicleIdentityResolution,
)
from vir.domain.enums import ProvenanceMethod

from product_integration.pgdr.handoff_mapper import map_resolution
from product_integration.vir.client import SERVICE_TOKEN_HEADER, VIRClient
from tests.conftest import make_vin_request

DECODE = SourceEvidence(source_id="vin_decoder", reported_value="ENG1", reliability="high",
                        method=ProvenanceMethod.DECODE, role="concordant", source_value="ENG1")
CONFIRMATION = SourceEvidence(source_id="driver_confirmation", reported_value="ENG1", reliability="medium",
                              method=ProvenanceMethod.USER_CONFIRMATION, role="user_confirmation", source_value="ENG1")


def _resolution(sources: list[SourceEvidence]) -> VehicleIdentityResolution:
    return VehicleIdentityResolution(
        request_id="REQ-CONF", resolution_id="VIR-RES-CONF",
        resolution_status=VIRResolutionStatus.PROVISIONALLY_RESOLVED,
        vehicle_identity=CanonicalVehicleIdentity(manufacturer="Peugeot", engine=Engine(engine_code="ENG1")),
        field_evidence=[FieldEvidence(field_path="engine.engine_code", resolved_value="ENG1", sources=sources)],
    )


class TestConfirmationOnlyValueIsNotPromoted:

    def test_confirmation_alone_reaches_pgdr_as_unknown(self):
        ctx = map_resolution(_resolution([CONFIRMATION]))
        assert ctx.vehicle_identity["engine"]["engine_code"] is None
        assert "engine.engine_code" in ctx.unresolved_fields

    def test_decoded_value_is_unchanged(self):
        ctx = map_resolution(_resolution([DECODE]))
        assert ctx.vehicle_identity["engine"]["engine_code"] == "ENG1"
        assert "engine.engine_code" not in ctx.unresolved_fields

    def test_concordant_confirmation_keeps_the_decoded_value(self):
        ctx = map_resolution(_resolution([DECODE, CONFIRMATION]))
        assert ctx.vehicle_identity["engine"]["engine_code"] == "ENG1"
        assert "engine.engine_code" not in ctx.unresolved_fields

    def test_other_fields_untouched(self):
        ctx = map_resolution(_resolution([CONFIRMATION]))
        assert ctx.vehicle_identity["manufacturer"] == "Peugeot"


class TestConfirmationThroughTheRealChain:

    async def test_vir_confirmation_survives_mirror_and_is_withheld_from_pgdr(self, vir_isolated_store, vir_service_env):
        import vir.api.routes as vir_routes
        headers = {SERVICE_TOKEN_HEADER: vir_service_env}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=vir_routes.app), base_url="http://vir.test") as h:
            client = VIRClient(h)
            resolution = await client.resolve(make_vin_request())
            assert resolution.vehicle_identity.engine.get("engine_code") is None  # the stub decodes no engine code
            r = await h.post(f"/v1/vehicle-identities/{resolution.resolution_id}/driver-confirmations",
                             headers=headers, json={"field_path": "engine.engine_code", "value": "CODEFICTIF"})
            assert r.status_code == 200, r.text
            mirrored = await client.get_resolution(resolution.resolution_id)

        payload = mirrored.model_dump(mode="json")                      # cpl_registration.py artifact payload
        methods = {s["method"] for fe in payload["field_evidence"] for s in fe["sources"]}
        assert "user_confirmation" in methods                           # provenance kept by PI-01's mirror

        ctx = map_resolution(VehicleIdentityResolution.model_validate(payload))  # case_orchestration.py path
        assert ctx.resolution_status.value == "provisionally_resolved"
        assert ctx.vehicle_identity["engine"]["engine_code"] is None
        assert "engine.engine_code" in ctx.unresolved_fields
