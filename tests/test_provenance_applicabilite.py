"""Passe identité, provenance et applicabilité: a driver confirmation crosses VIR -> PI -> PGDR with its real
provenance, and never becomes an established fact nor, alone, an applicable notice.

The real chain: VIR's app in REAL provider mode on FAKE transports (fictitious RegCheck and Vincario data,
no generation), PI-05's authenticated API (confirmation, correction, consultation, withdrawal), the CPL
artifact, PI-02's real map_resolution(), PGDR's real /api/v1/vir-handoff with a FICTIVE notice. No
PGDR_V1_DEV_VEHICLE, no development trial, no supplier call. One test per caller of the mapper: parcours
(parcours_routes.py), Photo-First (photo_intake.py), orchestration (case_orchestration.py). A fictive trial
proves the technical wiring, never the real applicability of any notice.
"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest
import yaml

import pgdr.v1_parcours as v1
import pgdr.web_app as pgdr_web
from pgdr import v1_applicabilite as va
from pgdr.models import Consent, InitialComplaint, UserContext
from pgdr.session_controller import SessionController
from vir.domain.models import VehicleIdentityResolution as VIRVehicleIdentityResolution

from product_integration.cpl_registration import VIRRegistrationOutcome, register_vir_resolution_result
from product_integration.orchestration.case_orchestration import start_vehicle_diagnostic
from product_integration.pgdr import photo_intake
from product_integration.pgdr.handoff_mapper import map_resolution
from product_integration.vir.client import SERVICE_TOKEN_HEADER, VIRClient

from tests import vir_real_mode_support as support
from tests.conftest import make_vin_request
from tests.test_case_orchestration import full_authority  # noqa: F401  (the orchestration's authority)
from tests.test_notice_parcours import (  # noqa: F401  (fixtures)
    make_app, open_parcours, pgdr, pgdr_calls, use_notice, user, vir_store,
)

NOTICE_VEHICLE = {"manufacturer": "MARQUE-FICTIVE", "model": "MODELE-FICTIF", "generation": "G-FICTIVE"}
PROVISIONAL_VIN = "VF1XXXXXXXXXXXXXX"     # VIR simulated fixture: manufacturer deduced, no model, no generation


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def new_case(client, **identifiers) -> tuple[str, str]:
    r = await client.post("/vehicles", json={"contact_idempotency_key": _key("c"), "asset_idempotency_key": _key("a")})
    assert r.status_code == 201, r.text
    v = r.json()
    body = {"contact_id": v["contact_id"], "asset_id": v["asset_id"], "request_id": _key("vir"),
            "registration_country_code": "FR", "consent": {"external_lookup_allowed": True},
            "case_idempotency_key": _key("case"), **identifiers}
    r = await client.post("/cases", json=body)
    assert r.status_code == 201, r.text
    return r.json()["case_id"], v["asset_id"]


@pytest.fixture
def real_vir(monkeypatch, vir_store, pgdr, tmp_path):
    """VIR in real mode on counting fake transports, behind PI's real app, and PGDR's notice for the
    fictitious vehicle with its applicability NOT established at notice level."""
    from vir.adapters.sqlite_persistence_adapter import SQLitePersistenceAdapter
    import vir.api.routes as vir_routes
    for name, value in support.FICTIVE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(vir_routes, "STORE", SQLitePersistenceAdapter(str(tmp_path / "vir_real.db")))
    support.permit_real_adapters(monkeypatch.setattr)
    regcheck, vincario = support.FakeRegCheckTransport(), support.FakeVincarioTransport()
    monkeypatch.setattr(vir_routes, "_DEFAULT_PROVIDERS", support.real_mode_providers(regcheck, vincario))
    application = make_app(pgdr, vir_routes.create_app(provider_mode="real"))
    use_notice(pgdr, NOTICE_VEHICLE, applicability_established=False)
    return application, regcheck, vincario


def attest(pgdr, asset_id: str, **over) -> None:
    """A FICTIVE attestation limited to one vehicle (the case's CPL asset) and the notice now in use."""
    catalogue = v1._wiring.repository.catalogue
    item = {"status": "VALIDE", "attested_by": "Fictive Owner", "verified_on": "2026-10-18",
            "document_id": catalogue.document.document_id, "catalogue_content_sha256": catalogue.content_sha256,
            "vehicle_ref": asset_id,
            "criteria": {k: {"value": v, "notice_source": {"kind": "printed_notice", "reference": "couverture fictive"},
                             "vehicle_source": {"kind": "registration_document", "reference": "rubrique fictive"}}
                         for k, v in NOTICE_VEHICLE.items()}}
    item.update(over)
    path = pgdr.tmp / f"applicabilite-{uuid.uuid4().hex}.yaml"
    path.write_text(yaml.safe_dump({"format": va.ATTESTATION_FORMAT, "attestations": [item]}, allow_unicode=True),
                    encoding="utf-8")
    v1._wiring.attestations = va.load_attestations(path)


async def confirm_generation(client, case_id: str) -> None:
    r = await client.post(f"/cases/{case_id}/vir/confirmations",
                          json={"field_path": "generation", "value": NOTICE_VEHICLE["generation"]})
    assert r.status_code == 200, r.text


# --- caller 1: the notice parcours (parcours_routes.py) -----------------------------------------------------

@pytest.mark.asyncio
async def test_confirmed_generation_crosses_the_chain_with_its_provenance_and_opens_nothing_alone(real_vir, pgdr):
    application, regcheck, vincario = real_vir
    client = await user(application, "prv")
    case_id, asset_id = await new_case(client, vin=support.VIN)
    before = (await client.get(f"/cases/{case_id}/vir")).json()
    await confirm_generation(client, case_id)
    after = (await client.get(f"/cases/{case_id}/vir")).json()
    assert after["exact_factory_configuration_known"] is False and before["exact_factory_configuration_known"] is False
    assert after["confidence"]["score"] <= before["confidence"]["score"]           # never raised

    r = await open_parcours(client, case_id)
    assert r["status"] == "applicability_not_confirmed" and r["page"] is None and v1._parcours == {}
    assert any("seule confirmation du conducteur" in x for x in r["reasons"])
    assert r["to_verify"] and "déjà validés" in r["next_action"]
    generation = {k["key"]: k for k in r["identity"]}["generation"]
    assert generation["value"] == NOTICE_VEHICLE["generation"]
    assert generation["provenance_label"].startswith("confirmé par le conducteur")

    (handoff,) = pgdr_calls(pgdr, "/api/v1/vir-handoff")
    sent = json.loads(handoff)
    assert sent["vehicle_identity"]["generation"] is None and "generation" in sent["unresolved_fields"]
    p = sent["field_provenance"]["generation"]
    assert (p["status"], p["value"]) == ("user_confirmed", NOTICE_VEHICLE["generation"])
    assert [(s["source_id"], s["method"]) for s in p["sources"]] == [("driver_confirmation", "user_confirmation")]
    assert all(s["method"] != "decode" for f in sent["field_provenance"].values() for s in f["sources"]
               if s["source_id"] == "driver_confirmation")
    assert sent["field_provenance"]["model"]["status"] == "provider_not_established"   # no promotion
    assert sent["confidence"]["score"] == after["confidence"]["score"]                 # handed on as VIR gave it
    assert sent["vehicle_ref"] == asset_id
    assert support.VIN.encode() not in handoff and support.PLATE.encode() not in handoff
    await client.aclose()


@pytest.mark.asyncio
async def test_attestation_for_this_vehicle_opens_and_not_for_another_owner(real_vir, pgdr):
    application, _, _ = real_vir
    owner_a, owner_b = await user(application, "pra"), await user(application, "prb")
    case_a, asset_a = await new_case(owner_a, vin=support.VIN)
    case_b, asset_b = await new_case(owner_b, vin=support.VIN)
    for client, case_id in ((owner_a, case_a), (owner_b, case_b)):
        await confirm_generation(client, case_id)
    attest(pgdr, asset_a)
    opened = await open_parcours(owner_a, case_a)
    assert opened["status"] == "opened" and opened["page"].startswith("/v1?p=V1-")
    pid = opened["page"].split("p=", 1)[1]
    assert v1._parcours[pid].applicability_basis == "attestation"
    assert v1._parcours[pid].vehicle["generation"] is None          # still not an admissible value elsewhere
    refused = await open_parcours(owner_b, case_b)                   # same fictitious identity, other vehicle
    assert refused["status"] == "applicability_not_confirmed"
    assert any("Aucune attestation" in x for x in refused["reasons"])
    assert (await owner_b.post(f"/cases/{case_a}/notice-parcours")).status_code == 404   # never another's case
    for c in (owner_a, owner_b):
        await c.aclose()


@pytest.mark.asyncio
async def test_attestation_for_another_notice_version_is_refused(real_vir, pgdr):
    application, _, _ = real_vir
    client = await user(application, "prc")
    case_id, asset_id = await new_case(client, vin=support.VIN)
    await confirm_generation(client, case_id)
    attest(pgdr, asset_id, catalogue_content_sha256="0" * 64)
    r = await open_parcours(client, case_id)
    assert r["status"] == "applicability_not_confirmed" and any("autre version" in x for x in r["reasons"])
    await client.aclose()


@pytest.mark.asyncio
async def test_missing_generation_and_contradiction_are_refused_explicitly(real_vir, pgdr):
    application, _, _ = real_vir
    client = await user(application, "prd")
    case_id, asset_id = await new_case(client, vin=support.VIN)
    attest(pgdr, asset_id)
    r = await open_parcours(client, case_id)                           # VIR gives no generation: nothing deduced
    assert r["status"] == "vehicle_identity_insufficient"
    assert any("La génération du véhicule n'est pas connue" in x for x in r["reasons"])
    assert {k["key"]: k for k in r["identity"]}["generation"]["provenance"] == "unknown"
    await client.aclose()


@pytest.mark.asyncio
async def test_different_model_label_is_refused_with_its_reason(real_vir, pgdr):
    application, _, _ = real_vir
    use_notice(pgdr, {**NOTICE_VEHICLE, "model": "MODELE-FICTIF NOUVEAU"}, applicability_established=False)
    client = await user(application, "pre")
    case_id, asset_id = await new_case(client, vin=support.VIN)
    await confirm_generation(client, case_id)
    r = await open_parcours(client, case_id)
    assert r["status"] == "vehicle_not_supported"
    assert any("Le modèle transmis (« MODELE-FICTIF »)" in x and "sans correspondance approchée" in x
               for x in r["reasons"])
    await client.aclose()


@pytest.mark.asyncio
async def test_no_supplier_call_on_confirmation_correction_consultation_or_withdrawal(real_vir, pgdr):
    application, regcheck, vincario = real_vir
    client = await user(application, "prf")
    case_id, _ = await new_case(client, vin=support.VIN)
    calls = (regcheck.calls, vincario.calls)
    await confirm_generation(client, case_id)
    r = await client.put(f"/cases/{case_id}/vir/confirmations/generation", json={"value": "G-FICTIVE-2"})
    assert r.status_code == 200, r.text
    assert (await client.get(f"/cases/{case_id}/vir")).status_code == 200
    await open_parcours(client, case_id)
    r = await client.delete(f"/cases/{case_id}/vir/confirmations/generation")
    assert r.status_code == 200, r.text
    assert (regcheck.calls, vincario.calls) == calls
    await client.aclose()


# --- caller 2: Photo-First (photo_intake.py) ----------------------------------------------------------------

async def _confirmed_resolution(vir_service_env):
    """A real VIR resolution whose generation rests on the driver's confirmation alone (VIR's simulated
    fixture deduces the manufacturer only), read back through PI-01's client and mirror."""
    import vir.api.routes as vir_routes
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=vir_routes.app), base_url="http://vir.test") as h:
        client = VIRClient(h)
        resolution = await client.resolve(make_vin_request(vin=PROVISIONAL_VIN))
        r = await h.post(f"/v1/vehicle-identities/{resolution.resolution_id}/driver-confirmations",
                         headers={SERVICE_TOKEN_HEADER: vir_service_env},
                         json={"field_path": "generation", "value": "G-FICTIVE"})
        assert r.status_code == 200, r.text
        return await client.get_resolution(resolution.resolution_id)


@pytest.mark.asyncio
async def test_photo_first_receives_the_confirmation_as_such_and_never_as_known(monkeypatch, vir_isolated_store,
                                                                                vir_service_env):
    mirrored = await _confirmed_resolution(vir_service_env)
    resolution = VIRVehicleIdentityResolution.model_validate(mirrored.model_dump(mode="json"))
    sent = []
    monkeypatch.setenv(photo_intake.PGDR_BASE_URL_ENV, "http://pgdr.test")
    monkeypatch.setenv(photo_intake.PGDR_HANDOFF_TOKEN_ENV, "fictive-photo-token")
    monkeypatch.setenv(pgdr_web.IDENTITY_HANDOFF_TOKEN_ENV, "fictive-photo-token")
    pgdr_web._photo_intakes.clear()

    class Recording(httpx.ASGITransport):
        async def handle_async_request(self, request):
            sent.append(json.loads(request.content))
            return await super().handle_async_request(request)

    async with httpx.AsyncClient(transport=Recording(app=pgdr_web.app)) as http:
        with pytest.raises(photo_intake.PhotoIntakeRefusedError):
            await photo_intake.request_photo_first_intake(resolution, http_client=http)
    (body,) = sent
    assert body["field_provenance"]["generation"]["status"] == "user_confirmed"
    assert body["vehicle_identity"]["generation"] is None and "generation" in body["unresolved_fields"]
    assert not pgdr_web._photo_intakes                                     # no reference set chosen on it


# --- caller 3: orchestration (case_orchestration.py) --------------------------------------------------------

@pytest.mark.asyncio
async def test_orchestration_hands_pgdr_the_confirmation_apart_from_known_values(full_authority, vir_isolated_store,
                                                                                vir_service_env):
    from product_integration.orchestration.case_orchestration import register_vehicle_for_contact
    from app.cpl.cases.lifecycle import create_case
    from app.db.engine import SessionLocal
    contact = register_vehicle_for_contact(
        asset_domain="AUTOMOTIVE", asset_type="PASSENGER_CAR", authority=full_authority,
        contact_idempotency_key=_key("contact"), asset_idempotency_key=_key("asset"))
    with SessionLocal() as session:
        case_id = create_case(session, primary_contact_id=contact.contact_id, asset_id=contact.asset_id,
                              domain="AUTOMOTIVE", case_type="VEHICLE_DIAGNOSTIC", authority=full_authority,
                              idempotency_key=_key("case")).object_id
        session.commit()
    mirrored = await _confirmed_resolution(vir_service_env)
    registered = register_vir_resolution_result(vir_resolution=mirrored, case_id=case_id, asset_id=contact.asset_id,
                                                authority=full_authority)
    assert registered.outcome == VIRRegistrationOutcome.SUCCESS
    start = await start_vehicle_diagnostic(
        case_id=case_id, session_controller=SessionController(),
        initial_complaint=InitialComplaint(free_text="A fictive noise."), user_context=UserContext(),
        consent=Consent(), authority=full_authority)
    ctx = start.pgdr_session.request.vehicle_identity_context
    assert ctx.field_provenance["generation"].status.value == "user_confirmed"
    assert ctx.vehicle_identity["generation"] is None and "generation" in ctx.unresolved_fields
    assert ctx == map_resolution(VIRVehicleIdentityResolution.model_validate(mirrored.model_dump(mode="json")))


def test_pgdr_suggests_a_confirmation_only_for_keys_vir_lets_the_driver_confirm():
    from vir.domain.driver_confirmation import CONFIRMABLE_FIELDS
    from pgdr.application.vehicle_applicability import APPLICABILITY_IDENTITY_FIELDS
    assert va.DRIVER_CONFIRMABLE_KEYS == set(APPLICABILITY_IDENTITY_FIELDS) & set(CONFIRMABLE_FIELDS)
