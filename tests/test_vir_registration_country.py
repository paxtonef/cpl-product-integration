"""VIR V1 registration country — VIR (application/request_validation.py,
commit 9d625d2) refuses any resolution whose registration.country_code is
absent, unknown or not enabled, for a VIN as for a plate, and never falls
back to France. PI-05 must forward the country the user chose, for both
identifiers, and must never supply one on the user's behalf. Without a
chosen country PI-05 now refuses the request itself: the plate or VIN does
not leave PI (it used to reach VIR, which refused it with VIR-ERR-011).

HTTP only, real VIR (ASGI), real PostgreSQL; fictitious identifiers."""
from __future__ import annotations

import uuid

from product_integration.cpl_registration import VIRRegistrationOutcome
from tests.test_product_api import _register_vehicle, api_client, vir_isolated_store  # noqa: F401 (fixtures)


async def _start(client, **identity) -> dict:
    veh = await _register_vehicle(client)
    body = {
        "contact_id": veh["contact_id"], "asset_id": veh["asset_id"], "request_id": f"cty-{uuid.uuid4().hex[:10]}",
        "consent": {"external_lookup_allowed": True}, "case_idempotency_key": f"case-{uuid.uuid4().hex[:10]}",
        **identity,
    }
    r = await client.post("/cases", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _refused_without_country(client, **identity) -> None:
    veh = await _register_vehicle(client)
    r = await client.post("/cases", json={
        "contact_id": veh["contact_id"], "asset_id": veh["asset_id"], "request_id": f"cty-{uuid.uuid4().hex[:10]}",
        "consent": {"external_lookup_allowed": True}, "case_idempotency_key": f"case-{uuid.uuid4().hex[:10]}",
        **identity,
    })
    assert r.status_code == 422, r.text
    assert r.json()["error_category"] == "INVALID_REQUEST"
    assert "FR" not in r.text and not any(str(v) in r.text for v in identity.values())
    assert (await client.get("/cases")).json()["cases"] == []    # nothing created


class TestVIRRegistrationCountry:

    async def test_vin_with_explicit_country_is_resolved(self, api_client):
        case = await _start(api_client, vin="VF3XXXXXXXXXXXXXX", registration_country_code="FR")
        assert case["outcome"] == VIRRegistrationOutcome.SUCCESS, case.get("detail")

    async def test_vin_without_country_is_refused_before_vir(self, api_client):
        await _refused_without_country(api_client, vin="VF3XXXXXXXXXXXXXX")

    async def test_plate_without_country_is_never_sent_as_france(self, api_client):
        await _refused_without_country(api_client, registration_number="AM-BIG-01")

    async def test_not_enabled_country_is_refused_not_replaced(self, api_client):
        case = await _start(api_client, vin="VF3XXXXXXXXXXXXXX", registration_country_code="DE")
        assert case["outcome"] == VIRRegistrationOutcome.VIR_TECHNICAL_FAILURE
        assert "FR" not in (case.get("vir_resolution_status") or "")
