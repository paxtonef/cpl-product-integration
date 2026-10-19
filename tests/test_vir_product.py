"""VIR in the product (PI-05 API): explicit country and plate or VIN,
explicit consent before any external lookup, a result view with provenance,
unknowns, contradictions, divergent evidence, set-aside candidates and the
providers' descriptive information kept apart from the normalized fields,
and the driver's confirmation of the seven existing fields with correction
and withdrawal.

VIR runs in REAL provider mode with its real RegCheck and Vincario adapters
on fake, call-counting transports (tests/vir_real_mode_support.py): no
simulated fixture, no fallback, governance permitted for the test only.
This proves the product wiring, not the real use of a provider. Every VIR
call PI makes is counted too. HTTP only, real PostgreSQL; fictitious data.
"""
from __future__ import annotations

import json
import logging
import uuid
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db.engine import SessionLocal

from product_integration.api.app import create_app
from product_integration.api.deps import get_vir_client
from product_integration.vir.client import VIRClient

from tests import vir_real_mode_support as support
from tests.auth_support import log_in, new_account

MISSING = "00000000-0000-4000-8000-000000000000"


class CountingASGITransport(httpx.ASGITransport):
    """Records every request PI sends to VIR (method, path)."""

    def __init__(self, app):
        super().__init__(app=app)
        self.calls: list[tuple[str, str]] = []

    async def handle_async_request(self, request):
        self.calls.append((request.method, request.url.path))
        return await super().handle_async_request(request)


@pytest.fixture
def real_vir(monkeypatch, tmp_path):
    from vir.adapters.sqlite_persistence_adapter import SQLitePersistenceAdapter
    import vir.api.routes as vir_routes
    for name, value in support.FICTIVE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(vir_routes, "STORE", SQLitePersistenceAdapter(str(tmp_path / "vir_real_mode.db")))
    regcheck, vincario = support.FakeRegCheckTransport(), support.FakeVincarioTransport()
    support.permit_real_adapters(monkeypatch.setattr)
    monkeypatch.setattr(vir_routes, "_DEFAULT_PROVIDERS", support.real_mode_providers(regcheck, vincario))
    vir_app = vir_routes.create_app(provider_mode="real")
    return SimpleNamespace(app=vir_app, regcheck=regcheck, vincario=vincario,
                           transport=CountingASGITransport(vir_app))


def provider_calls(vir) -> int:
    return vir.regcheck.calls + vir.vincario.calls


@pytest.fixture
def app(real_vir):
    async def override_vir_client():
        async with httpx.AsyncClient(transport=real_vir.transport, base_url="http://vir.test") as c:
            yield VIRClient(c)

    application = create_app()
    application.dependency_overrides[get_vir_client] = override_vir_client
    return application


async def _user(app, prefix: str) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test")
    client.identity = await log_in(client, *new_account(prefix))
    return client


@pytest_asyncio.fixture
async def user_a(app):
    client = await _user(app, "vira")
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def user_b(app):
    client = await _user(app, "virb")
    yield client
    await client.aclose()


def _key(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}"


async def _vehicle(client) -> dict:
    r = await client.post("/vehicles", json={"contact_idempotency_key": _key("c"), "asset_idempotency_key": _key("a")})
    assert r.status_code == 201, r.text
    return r.json()


def _case_body(vehicle: dict, **identifiers) -> dict:
    body = {"contact_id": vehicle["contact_id"], "asset_id": vehicle["asset_id"], "request_id": _key("vir"),
            "registration_country_code": "FR", "consent": {"external_lookup_allowed": True},
            "case_idempotency_key": _key("case")}
    body.update(identifiers)
    return body


async def _case(client, **identifiers) -> dict:
    r = await client.post("/cases", json=_case_body(await _vehicle(client), **identifiers))
    assert r.status_code == 201, r.text
    return r.json()


async def _view(client, case_id: str) -> dict:
    r = await client.get(f"/cases/{case_id}/vir")
    assert r.status_code == 200, r.text
    return r.json()


def _field(view: dict, path: str) -> dict:
    return next(f for f in view["fields"] if f["field_path"] == path)


def _confirmable(view: dict, path: str) -> dict:
    return next(c for c in view["confirmations"] if c["field_path"] == path)


def _vir_executions(case_id: str) -> int:
    with SessionLocal() as s:
        return s.execute(text("SELECT count(*) FROM cpl.runner_executions WHERE case_id = :c AND runner_type = 'VIR'"),
                         {"c": case_id}).scalar()


# -- entry: country, identifier, consent ---------------------------------------------------

class TestEntryAndConsent:

    async def test_no_identifier_leaves_pi_without_explicit_consent(self, app, real_vir, user_a):
        vehicle = await _vehicle(user_a)
        for identifiers in ({"registration_number": support.PLATE}, {"vin": support.VIN}):
            body = _case_body(vehicle, **identifiers)
            body["consent"] = {"external_lookup_allowed": False}
            r = await user_a.post("/cases", json=body)
            assert r.status_code == 422, r.text
            assert r.json()["error_category"] == "CONSENT_REQUIRED"
            assert support.PLATE not in r.text and support.VIN not in r.text
        assert real_vir.transport.calls == [] and provider_calls(real_vir) == 0
        assert (await user_a.get("/cases")).json()["cases"] == []

    async def test_an_identifier_needs_an_explicit_country(self, app, real_vir, user_a):
        vehicle = await _vehicle(user_a)
        body = _case_body(vehicle, registration_number=support.PLATE)
        body["registration_country_code"] = None
        r = await user_a.post("/cases", json=body)
        assert r.status_code == 422 and r.json()["error_category"] == "INVALID_REQUEST"
        assert real_vir.transport.calls == [] and provider_calls(real_vir) == 0

    async def test_plate_goes_to_the_real_regcheck_adapter_once(self, app, real_vir, user_a):
        case = await _case(user_a, registration_number=support.PLATE)
        assert (real_vir.regcheck.calls, real_vir.vincario.calls) == (1, 0)
        assert case["vir_resolution_status"]


# -- result view ------------------------------------------------------------------------

class TestResultView:

    async def test_provenance_unknowns_and_descriptive_information_apart(self, app, real_vir, user_a):
        case = await _case(user_a, registration_number=support.PLATE)
        calls = provider_calls(real_vir)
        view = await _view(user_a, case["case_id"])
        assert provider_calls(real_vir) == calls                       # reading the result consults no provider
        assert view["resolution_status"] == "provisionally_resolved" and view["simulated"] is True
        assert view["registration_country"] == "FR"
        manufacturer = _field(view, "manufacturer")
        assert manufacturer["value"] == "MARQUE-FICTIVE"
        assert [s["source_id"] for s in manufacturer["sources"]] == ["provider-fr-regcheck"]
        assert manufacturer["status_label"]
        assert "model_year" in view["unknown_fields"] and "generation" in view["unknown_fields"]
        descriptive = {d["provider_field"]: d for d in view["descriptive_info"]}
        assert descriptive["libVersion"]["value"] == "VERSION-FICTIVE" and descriptive["puissanceDyn"]["unit"] == "HP"
        normalized_paths = {f["field_path"] for f in view["fields"]}
        assert not normalized_paths & {"libVersion", "BodyStyle", "puissanceDyn", "CNIT", "version", "trim"}
        assert view["exact_factory_configuration_known"] is False

    async def test_plate_and_vin_never_travel_back(self, app, real_vir, user_a):
        for identifiers in ({"registration_number": support.PLATE}, {"vin": support.VIN}):
            case = await _case(user_a, **identifiers)
            r = await user_a.get(f"/cases/{case['case_id']}/vir")
            assert support.PLATE not in r.text and support.VIN not in r.text
            assert not any(f["field_path"].startswith("identifiers") for f in r.json()["fields"])
            r = await user_a.get(f"/executions/{case['vir_execution_id']}/artifact")
            assert r.status_code == 200
            assert support.PLATE not in r.text and support.VIN not in r.text

    async def test_refresh_is_explicit_and_consults_no_provider(self, app, real_vir, user_a):
        case = await _case(user_a, vin=support.VIN)
        calls = provider_calls(real_vir)
        first, second = await _view(user_a, case["case_id"]), await _view(user_a, case["case_id"])
        assert first == second and provider_calls(real_vir) == calls
        assert [c for c in real_vir.transport.calls if c[1].endswith("/resolve")] == [("POST", "/v1/vehicle-identities/resolve")]


# -- driver confirmation of the seven fields ---------------------------------------------------

class TestDriverConfirmation:

    async def test_seven_fields_offered_never_preselected(self, app, real_vir, user_a):
        case = await _case(user_a, vin=support.VIN)
        view = await _view(user_a, case["case_id"])
        assert [c["field_path"] for c in view["confirmations"]] == [
            "fuel.primary_type", "transmission.type", "generation", "engine.engine_code", "transmission.gears",
            "drivetrain", "model_year"]
        assert all(c["confirmation"] is None for c in view["confirmations"])
        assert "front_wheel_drive" in _confirmable(view, "drivetrain")["choices"]
        assert _confirmable(view, "model_year")["proposals"] == [{"value": 2019, "sources": ["provider-vincario-vin"]}]

    async def test_confirm_correct_withdraw_without_any_provider_call(self, app, real_vir, user_a):
        case = await _case(user_a, vin=support.VIN)
        case_id = case["case_id"]
        before = await _view(user_a, case_id)
        calls, executions = provider_calls(real_vir), _vir_executions(case_id)

        r = await user_a.post(f"/cases/{case_id}/vir/confirmations",
                              json={"field_path": "drivetrain", "value": "front_wheel_drive"})
        assert r.status_code == 200, r.text
        confirmed = await _view(user_a, case_id)
        drivetrain = _field(confirmed, "drivetrain")
        assert drivetrain["value"] == "front_wheel_drive" and drivetrain["status"] == "user_confirmed"
        assert [s["method"] for s in drivetrain["sources"]] == ["user_confirmation"]   # never "decode"
        assert _confirmable(confirmed, "drivetrain")["confirmation"] == {"value": "front_wheel_drive", "applied": True}
        assert confirmed["confidence"]["score"] <= before["confidence"]["score"]   # no artificial increase
        assert confirmed["resolution_status"] == before["resolution_status"]
        assert confirmed["exact_factory_configuration_known"] is False

        r = await user_a.put(f"/cases/{case_id}/vir/confirmations/drivetrain", json={"value": "rear_wheel_drive"})
        assert r.status_code == 200, r.text
        assert _field(await _view(user_a, case_id), "drivetrain")["value"] == "rear_wheel_drive"

        r = await user_a.delete(f"/cases/{case_id}/vir/confirmations/drivetrain")
        assert r.status_code == 200, r.text
        withdrawn = await _view(user_a, case_id)
        assert _confirmable(withdrawn, "drivetrain")["confirmation"] is None
        assert _confirmable(withdrawn, "drivetrain")["value"] is None
        assert not [f for f in withdrawn["fields"] if f["field_path"] == "drivetrain"]
        assert withdrawn["confirmations"] == before["confirmations"]

        assert provider_calls(real_vir) == calls                          # zero provider call for all three
        assert not [c for c in real_vir.transport.calls if c[1].endswith("/resolve")][1:]
        assert _vir_executions(case_id) == executions + 3                 # each state registered in CPL
        history = (await user_a.get(f"/cases/{case_id}/history")).json()
        latest = [e for e in history["executions"] if e["runner_type"] == "VIR"][-1]
        artifact = (await user_a.get(f"/executions/{latest['execution_id']}/artifact")).json()
        assert artifact["payload"]["user_confirmed_fields"] == []

    async def test_a_different_value_is_kept_as_divergent_evidence_not_applied(self, app, real_vir, user_a):
        case = await _case(user_a, vin=support.VIN)
        r = await user_a.post(f"/cases/{case['case_id']}/vir/confirmations",
                              json={"field_path": "model_year", "value": 2020})
        assert r.status_code == 200, r.text
        view = await _view(user_a, case["case_id"])
        model_year = _field(view, "model_year")
        assert model_year["value"] == 2019 and model_year["status"] != "user_confirmed"
        assert {"source_id": "driver_confirmation", "value": 2020, "method": "user_confirmation"} in model_year["divergent"]
        assert view["resolution_status"] == "contradictory"
        [contradiction] = [c for c in view["contradictions"] if c["field_path"] == "model_year"]
        assert {v["value"] for v in contradiction["values"]} == {2019, 2020}
        assert _confirmable(view, "model_year")["confirmation"] == {"value": 2020, "applied": False}

    async def test_unknown_field_and_invalid_value_are_refused_and_change_nothing(self, app, real_vir, user_a):
        case = await _case(user_a, vin=support.VIN)
        case_id = case["case_id"]
        executions, vir_calls = _vir_executions(case_id), len(real_vir.transport.calls)
        r = await user_a.post(f"/cases/{case_id}/vir/confirmations", json={"field_path": "engine.power_kw", "value": 90})
        assert r.status_code == 422 and r.json()["error_category"] == "INVALID_REQUEST"
        r = await user_a.delete(f"/cases/{case_id}/vir/confirmations/identifiers.vin")
        assert r.status_code == 422
        assert len(real_vir.transport.calls) == vir_calls                  # refused by PI, VIR not called
        r = await user_a.post(f"/cases/{case_id}/vir/confirmations", json={"field_path": "drivetrain", "value": "nope"})
        assert r.status_code == 422 and r.json()["error_category"] == "VIR_INPUT_REFUSED"
        assert r.json()["vir_error_code"] == "VIR-ERR-019" and "nope" not in r.text
        assert _vir_executions(case_id) == executions

    async def test_identity_is_frozen_once_a_diagnostic_has_started(self, app, real_vir, user_a):
        case = await _case(user_a, vin=support.VIN)
        r = await user_a.post(f"/cases/{case['case_id']}/diagnostics",
                              json={"complaint_text": "The engine makes a strange noise when accelerating."})
        assert r.status_code in (200, 201), r.text
        executions, vir_calls = _vir_executions(case["case_id"]), len(real_vir.transport.calls)
        r = await user_a.post(f"/cases/{case['case_id']}/vir/confirmations",
                              json={"field_path": "drivetrain", "value": "front_wheel_drive"})
        assert r.status_code == 409 and r.json()["error_category"] == "CONFLICT"
        assert _vir_executions(case["case_id"]) == executions and len(real_vir.transport.calls) == vir_calls
        assert (await _view(user_a, case["case_id"]))["confirmations_locked"] is True


# -- clarification ------------------------------------------------------------------------------

class TestClarification:

    async def test_unknown_question_id_is_refused_by_pi_before_vir(self, app, real_vir, user_a):
        case = await _case(user_a, vin=support.VIN)
        executions, vir_calls, calls = _vir_executions(case["case_id"]), len(real_vir.transport.calls), provider_calls(real_vir)
        for answers in ([{"question_id": "no-such-question", "value": "x"}], []):
            r = await user_a.post(f"/cases/{case['case_id']}/vir/clarifications", json={"answers": answers})
            assert r.status_code == 422, r.text
            assert r.json()["error_category"] == "CLARIFICATION_REFUSED"
        assert len(real_vir.transport.calls) == vir_calls and provider_calls(real_vir) == calls
        assert _vir_executions(case["case_id"]) == executions


# -- two users -------------------------------------------------------------------------------

class TestOwnership:

    async def test_cross_user_refusals_match_missing_and_change_nothing(self, app, real_vir, user_a, user_b):
        case = await _case(user_a, vin=support.VIN)
        case_id = case["case_id"]
        before = await _view(user_a, case_id)
        vir_calls, executions = len(real_vir.transport.calls), _vir_executions(case_id)
        probes = [
            ("GET", "/cases/{c}/vir", None),
            ("POST", "/cases/{c}/vir/confirmations", {"field_path": "drivetrain", "value": "front_wheel_drive"}),
            ("PUT", "/cases/{c}/vir/confirmations/drivetrain", {"value": "front_wheel_drive"}),
            ("DELETE", "/cases/{c}/vir/confirmations/drivetrain", None),
            ("POST", "/cases/{c}/vir/clarifications", {"answers": [{"question_id": "q", "value": "v"}]}),
        ]
        for method, template, body in probes:
            foreign = await user_b.request(method, template.format(c=case_id), json=body)
            missing = await user_b.request(method, template.format(c=MISSING), json=body)
            assert foreign.status_code == missing.status_code == 404, (template, foreign.text)
            assert foreign.content == missing.content
        assert len(real_vir.transport.calls) == vir_calls                 # B never reached VIR
        assert _vir_executions(case_id) == executions
        assert await _view(user_a, case_id) == before


# -- logs ----------------------------------------------------------------------------------------

class TestLogs:

    async def test_no_identifier_secret_or_login_in_logs(self, app, real_vir, user_a, caplog):
        caplog.set_level(logging.DEBUG)
        case = await _case(user_a, vin=support.VIN)
        await _case(user_a, registration_number=support.PLATE)
        await _view(user_a, case["case_id"])
        await user_a.post(f"/cases/{case['case_id']}/vir/confirmations", json={"field_path": "drivetrain", "value": "nope"})
        await user_a.post(f"/cases/{case['case_id']}/vir/confirmations",
                          json={"field_path": "drivetrain", "value": "front_wheel_drive"})
        logged = "\n".join(record.getMessage() for record in caplog.records)
        secrets_ = [support.PLATE, support.VIN, *support.FICTIVE_ENV.values()]
        assert not [s for s in secrets_ if s in logged and s not in ("true",)]
        import os
        assert os.environ["VIR_SERVICE_TOKEN"] not in logged


# -- presentation (VIR's own model and rules, PI does not re-implement them) ------------------------

def test_view_keeps_set_aside_candidates_and_divergent_values_apart():
    from vir.domain.models import (
        CanonicalVehicleIdentity, Engine, ExcludedCandidate, FieldEvidence, Identifiers, ProviderDescriptiveInfo,
        SourceEvidence, VehicleCandidate, VehicleIdentityResolution,
    )
    from product_integration.vir.presentation import build_view

    identity = CanonicalVehicleIdentity(manufacturer="MARQUE-FICTIVE", model_year=2019, engine=Engine(power_kw=81),
                                        identifiers=Identifiers(vin=support.VIN, registration_number=support.PLATE))
    set_aside = VehicleCandidate(candidate_id="CAND-2", identity=CanonicalVehicleIdentity(
        manufacturer="MARQUE-FICTIVE", engine=Engine(power_kw=66), identifiers=Identifiers(vin=support.VIN)),
        source_ids=["provider-vincario-vin"])
    resolution = VehicleIdentityResolution(
        request_id="r", resolution_id="VIR-RES-FICTIVE", resolution_status="provisionally_resolved",
        vehicle_identity=identity,
        excluded_candidates=[ExcludedCandidate(candidate=set_aside, field_path="engine.power_kw", declared_value=81,
                                               candidate_value=66, reason_label="Puissance différente de la vôtre")],
        provider_descriptive_info=[ProviderDescriptiveInfo(source_id="provider-fr-regcheck", provider_field="libVersion",
                                                           label="Description de version fournie", value="VERSION-FICTIVE")],
        field_evidence=[
            FieldEvidence(field_path="model_year", resolved_value=2019, sources=[
                SourceEvidence(source_id="provider-vincario-vin", reported_value=2019, reliability="medium",
                               method="provider", role="concordant", source_value=2019),
                SourceEvidence(source_id="driver_confirmation", reported_value=2020, reliability="low",
                               method="user_confirmation", role="user_confirmation", source_value=2020)]),
            FieldEvidence(field_path="identifiers.vin", resolved_value=support.VIN, sources=[
                SourceEvidence(source_id="provider-vincario-vin", reported_value=support.VIN, reliability="high")]),
        ],
    )
    view = build_view(resolution.model_dump(mode="json"))
    dumped = json.dumps(view)
    assert support.VIN not in dumped and support.PLATE not in dumped
    [excluded] = view["excluded_candidates"]
    assert excluded == {"field_path": "engine.power_kw", "reason": "declared_value_mismatch",
                        "reason_label": "Puissance différente de la vôtre", "declared_value": 81, "candidate_value": 66,
                        "source_ids": ["provider-vincario-vin"], "declaration_verified": False}
    assert view["descriptive_info"][0]["label"] == "Description de version fournie"
    model_year = _field(view, "model_year")
    assert [s["source_id"] for s in model_year["sources"]] == ["provider-vincario-vin"]
    assert model_year["divergent"] == [{"source_id": "driver_confirmation", "value": 2020, "method": "user_confirmation"}]
